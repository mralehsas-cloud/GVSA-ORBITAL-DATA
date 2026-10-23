import contextlib
import io
import json
from pathlib import Path
import socket
import ssl
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import omm_source
import publish


class TestNetworkDiagnostics(unittest.TestCase):
    def check_reason(self, reason):
        with patch.object(omm_source, 'build_opener') as opener:
            opener.return_value.open.side_effect = URLError(reason)
            with self.assertRaises(RuntimeError) as caught:
                omm_source.download(omm_source.ISS_URL)
        self.assertIn(type(reason).__name__, str(caught.exception))
        self.assertIn(str(reason), str(caught.exception))

    def test_dns_reason(self):
        self.check_reason(socket.gaierror(-2, 'Name or service not known'))

    def test_tls_reason(self):
        self.check_reason(ssl.SSLCertVerificationError(1, 'certificate verify failed'))

    def test_timeout_reason(self):
        self.check_reason(TimeoutError('timed out'))

    def test_http_403_preserved(self):
        with patch.object(omm_source, 'build_opener') as opener:
            opener.return_value.open.side_effect = HTTPError(omm_source.ISS_URL, 403, 'Forbidden', {}, None)
            with self.assertRaisesRegex(RuntimeError, '^UPSTREAM_HTTP_403$'):
                omm_source.download(omm_source.ISS_URL)


class TestOperationalStatus(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.dest = self.root / 'orbital'
        self.dest.mkdir()
        self.state = self.root / 'state.json'
        self.now = 1792762520.0
        self.before = {}
        for filename in ('iss.json', 'starlink-sample.json'):
            self.before[filename] = b'last-good-snapshot\n'
            (self.dest / filename).write_bytes(self.before[filename])

    def run_execute(self, feeds, downloader):
        self.state.write_text(json.dumps({'schema':'gvsa-public-orbit-1','feeds':feeds}))
        with patch.object(publish, 'STATE', self.state), patch.object(publish, 'DEST', self.dest):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                result = publish.execute(self.now, downloader)
        for filename, content in self.before.items():
            self.assertEqual((self.dest / filename).read_bytes(), content)
        return result, json.loads(self.state.read_text()), json.loads((self.dest / 'update-status.json').read_text())

    def no_request(self, url):
        self.fail('Unexpected network request: ' + url)

    def test_backoff_keeps_failure_and_snapshots(self):
        feeds = {kind: {'last_error':'UPSTREAM_HTTP_403','no_request_before_unix':self.now+3600} for kind in publish.SOURCES}
        result, state, status = self.run_execute(feeds, self.no_request)
        self.assertEqual(result, 1)
        for kind in feeds:
            self.assertEqual(status['feeds'][kind]['status'], 'PROVIDER_BACKOFF')
            self.assertEqual(state['feeds'][kind]['no_request_before_unix'], self.now+3600)
            self.assertEqual(status['feeds'][kind]['error'], 'UPSTREAM_HTTP_403')

    def test_normal_cooldown_is_not_failure(self):
        feeds = {kind: {'last_attempt_unix':self.now-60} for kind in publish.SOURCES}
        result, _, status = self.run_execute(feeds, self.no_request)
        self.assertEqual(result, 0)
        self.assertTrue(all(v['status']=='SIX_HOUR_COOLDOWN' for v in status['feeds'].values()))

    def test_provider_failure_stops_requests_and_sets_backoff(self):
        calls = []
        def reject(url):
            calls.append(url)
            raise RuntimeError('UPSTREAM_HTTP_403')
        result, state, status = self.run_execute({}, reject)
        self.assertEqual(result, 1)
        self.assertEqual(calls, [publish.SOURCES['iss'][0]])
        self.assertEqual(state['feeds']['iss']['no_request_before_unix'], self.now+86400)
        self.assertEqual(status['feeds']['starlink']['status'], 'SKIPPED_AFTER_PROVIDER_ERROR')

    def test_backoff_without_prior_error_not_failure(self):
        feeds = {kind: {'no_request_before_unix':self.now+3600} for kind in publish.SOURCES}
        result, _, _ = self.run_execute(feeds, self.no_request)
        self.assertEqual(result, 0)

import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from unittest import TestCase
from datetime import datetime,timezone
from publish import incoming_is_newer, valid_existing, SOURCES, INTERVAL, ERROR_BACKOFF
from omm_source import sample, validated, parse_payload

class TestOrbits(TestCase):
    def setUp(self):
        self.now=datetime(2026,10,16,12,0,tzinfo=timezone.utc).timestamp()
        self.template=dict(NORAD_CAT_ID=25544,OBJECT_NAME='ISS (ZARYA)',EPOCH='2026-10-16T11:00:00Z',MEAN_MOTION=15.5,ECCENTRICITY=0.0001,INCLINATION=51.6,RA_OF_ASC_NODE=30.,ARG_OF_PERICENTER=15.,MEAN_ANOMALY=300.,BSTAR=0.0001,MEAN_MOTION_DOT=0.0,MEAN_MOTION_DDOT=0.0)
    def test_iss(self):
        self.assertIsNotNone(validated(self.template,'iss',self.now))
        self.assertEqual(len(sample([self.template],'iss',self.now)),1)
    def test_reject_future(self):
        self.assertIsNone(validated({**self.template,'EPOCH':'2032-01-01T00:00:00Z'},'iss',self.now))
    def test_reject_invalid_numerics(self):
        self.assertIsNone(validated({**self.template,'ECCENTRICITY':1.5},'iss',self.now))
    def test_starlink_36(self):
        arr=[{**self.template,'NORAD_CAT_ID':50000+i,'OBJECT_NAME':f'STARLINK-{i}'} for i in range(50)]
        self.assertEqual(len(sample(arr,'starlink',self.now)),36)
    def test_starlink_duplicates(self):
        arr=[{**self.template,'NORAD_CAT_ID':50000+i//2,'OBJECT_NAME':f'STARLINK-{i//2}'} for i in range(70)]
        self.assertRaises(ValueError,sample,arr,'starlink',self.now)
    def test_no_epoch_regression(self):
        self.assertFalse(incoming_is_newer('iss',[self.template],[self.template]))
        self.assertTrue(incoming_is_newer('iss',[self.template],[{**self.template,'EPOCH':'2026-10-15T11:00:00Z'}]))
    def test_no_fake_writes(self):
        self.assertEqual(INTERVAL,21600)
        self.assertEqual(ERROR_BACKOFF,86400)
    def test_names(self):
        self.assertEqual(SOURCES['iss'][1],'iss.json')
        self.assertEqual(SOURCES['starlink'][1],'starlink-sample.json')
    def test_reject_empty_provider_payload(self):
        with self.assertRaises(ValueError):parse_payload('iss',b'',self.now)
    def test_old_existing_can_compare(self):
        self.assertTrue(valid_existing('iss',[self.template]))


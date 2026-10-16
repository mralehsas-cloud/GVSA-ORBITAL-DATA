# GVSA IQ200 — Public orbital data relay (no FTPS password)

هذا المستودع **عام ومخصص حصراً للبيانات المدارية غير السرية**. يحفظ فقط ملفات OMM الأصلية الموثوقة لـ ISS وعينة من 36 قمراً من Starlink. لا توجد هنا بيانات الدخول إلى الاستضافة.

المستودع المطلوب بالضبط: `mralehsas-cloud/GVSA-ORBITAL-DATA` — **Public**. أبقِ المستودع القديم `GVSA-AUTO-UPDATE` خاصاً ولا تغيره.

## التثبيت أول مرة

1. أنشئ مستودع GitHub عاماً فارغاً باسم `GVSA-ORBITAL-DATA` تحت الحساب `mralehsas-cloud` (بدون README مبدئي).
2. ارفع مجلد `automation` كاملاً بصفحـة **Add file → Upload files** ثم **Commit changes**، واحتفظ بمسارات Python كما هي.
3. ملف `.github/workflows/update-orbits.yml` يحتاج رفعاً مع مجلده إلى الجذر. إذا لم يقبل GitHub المجلد المخفي، افتح **Add file → Create new file** واكتب المسار `.github/workflows/update-orbits.yml`، ثم الصق فيه **كامل نص الملف الأصلي** من الحزمة (المفكرة)، واضغط **Commit changes**. راقب ألا يكون `0 lines`.
4. في GitHub: **Settings → Actions → General → Workflow permissions** تأكد من سماح المستودع بـ **Read and write permissions**، إذا لم تكن مفعّلة؛ لا تغيّر صلاحيات مؤسسة أخرى.
5. افتح **Actions → GVSA - public ISS and Starlink OMM refresh → Run workflow** لأول مرة؛ افحص النتيجة. إذا رفض المصدر HTTP 403 فلا تكرر الطلب؛ النظام يحفظ آخر ملف صالح ويتوقف مؤقتاً.
6. تأكد من ظهور `orbital/iss.json` و`orbital/starlink-sample.json` بعد أول تحديث ناجح. صفحة `orbital/update-status.json` تعرض حالة آخر محاولة — لا تثبت وحدها حداثة EPOCH.

7. بعد نجاح النظام العام، عطّل سير العمل القديم داخل المستودع الخاص `GVSA-AUTO-UPDATE` من قائمة Actions → اسم سير العمل → زر النقاط `...` → Disable workflow. لا تحذفه، لكن لا نريد جدولين متوازيين.

## ربط موقع GVSA

ارفع ملفات حزمة **GVSA_SITE_PUBLIC_ORBITS_PATCH.zip** بواسطة FileZilla فوق النسخة الحالية داخل مجلد `GVSA/` مع الحفاظ على المسارات. **لا تحذف** ملف `data/de440.bsp`، ولا ملفَي ISS وStarlink المحليين، ولا مجلد `api/cache`. الملفات المحلية احتياطية فقط. الأفضل حفظ نسخة من الملفات التي ستُستبدل قبل الرفع.

بعد إنشاء المستودع وتشغيله ورفع تحديث الموقع، افتح:
- `https://ai.astronomycenter.net/GVSA/`
- `https://ai.astronomycenter.net/GVSA/diagnostics.html`
- `https://raw.githubusercontent.com/mralehsas-cloud/GVSA-ORBITAL-DATA/main/orbital/update-status.json`

عند فشل GitHub تبقى الملفات المحلية احتياطية، إذا لم تتجاوز حد صلاحية 72 ساعة. لا يتم اختراع الحقب المدارية، ولا تتحوّل البيانات القديمة إلى خضراء بتغيير وقت التنزيل.

## سياسة ومصدر البيانات

CelesTrak https://celestrak.org/usage-policy.php

الفاصل 6 ساعات بين المحاولات، مع 24 ساعة تهدئة على خطأ المصدر، دون إعادة المحاولة ضمن نفس التشغيل. الجدولة في GitHub تقديرية وقد تتأخر أو تُعطّل عند توقف نشاط المستودع. يجب مراقبة Actions أول مرة وبعدها دورياً.

**الاختبارات المحلية لا تعني تشغيل الجدولة في حسابك أو تحققاً ميدانياً من الدقة المدارية.**

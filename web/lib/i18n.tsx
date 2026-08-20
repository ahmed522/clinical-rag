"use client";

import { createContext, useContext, useEffect, useState } from "react";

/**
 * Interface chrome only — nav, buttons, labels, headings, statuses,
 * errors. The chat surface (patient messages, assistant answers,
 * citations, refusals) never reads from this dictionary and stays
 * English/LTR in both languages; see .chat-ltr in globals.css and the
 * chat components, which hardcode their strings rather than translate.
 */
const dict = {
  appName: { ar: "طبيبك", en: "Tabeebak" },

  // auth
  login: { ar: "تسجيل الدخول", en: "Log in" },
  logout: { ar: "تسجيل الخروج", en: "Log out" },
  email: { ar: "البريد الإلكتروني", en: "Email" },
  password: { ar: "كلمة المرور", en: "Password" },
  registerClinic: { ar: "تسجيل عيادة جديدة", en: "Register a clinic" },
  clinicName: { ar: "اسم العيادة", en: "Clinic name" },
  specialty: { ar: "التخصص", en: "Specialty" },
  adminEmail: { ar: "بريد مسؤول العيادة", en: "Admin email" },
  createClinic: { ar: "إنشاء العيادة", en: "Create clinic" },
  alreadyHaveAccount: { ar: "لديك حساب بالفعل؟", en: "Already have an account?" },
  needClinic: { ar: "عيادتك غير مسجلة؟", en: "Need to register a clinic?" },
  signingIn: { ar: "جارٍ تسجيل الدخول…", en: "Signing in…" },
  invalidCredentials: { ar: "البريد الإلكتروني أو كلمة المرور غير صحيحة", en: "Incorrect email or password" },
  connectionError: { ar: "تعذّر الاتصال بالخدمة. تحقق من الإنترنت ثم حاول مرة أخرى.", en: "Unable to reach the service. Check your connection and try again." },

  // nav / shell
  documents: { ar: "المستندات", en: "Documents" },
  doctors: { ar: "الأطباء", en: "Doctors" },
  chat: { ar: "المحادثة", en: "Chat" },
  appointments: { ar: "المواعيد", en: "Appointments" },
  myRecords: { ar: "سجلي الطبي", en: "My records" },
  clinicPanel: { ar: "لوحة العيادة", en: "Clinic panel" },

  // documents
  uploadDocument: { ar: "رفع مستند جديد", en: "Upload a document" },
  documentTitle: { ar: "عنوان المستند", en: "Document title" },
  publisher: { ar: "الناشر", en: "Publisher" },
  upload: { ar: "رفع", en: "Upload" },
  uploading: { ar: "جارٍ الرفع…", en: "Uploading…" },
  verified: { ar: "موثّق", en: "Verified" },
  pendingReview: { ar: "بانتظار المراجعة", en: "Pending review" },
  documentUploaded: { ar: "تم الرفع", en: "Uploaded" },
  processingDocument: { ar: "جارٍ تجهيز المستند", en: "Processing" },
  readyForReview: { ar: "جاهز للمراجعة", en: "Ready for review" },
  documentFailed: { ar: "فشل التجهيز", en: "Processing failed" },
  documentProcessingFailed: { ar: "تعذّر تجهيز هذا المستند.", en: "This document could not be processed." },
  markVerified: { ar: "تأكيد التوثيق", en: "Mark verified" },
  usedInPatientAnswers: { ar: "متاح لإجابات المرضى", en: "Used in patient answers" },
  excludedUntilVerified: { ar: "مستبعد من إجابات المرضى لحد ما يتوثّق", en: "Excluded from patient answers until verified" },
  excludedUntilReady: { ar: "مستبعد من إجابات المرضى حتى يكتمل التجهيز", en: "Excluded from patient answers until processing completes" },
  noDocumentsYet: { ar: "لا توجد مستندات بعد.", en: "No documents yet." },
  pages: { ar: "صفحة", en: "pages" },
  chunks: { ar: "مقطع", en: "chunks" },

  // doctors
  addDoctor: { ar: "إضافة طبيب", en: "Add doctor" },
  doctorName: { ar: "اسم الطبيب", en: "Doctor name" },
  available: { ar: "متاح", en: "Available" },
  unavailable: { ar: "غير متاح", en: "Unavailable" },
  add: { ar: "إضافة", en: "Add" },
  noDoctorsYet: { ar: "لا يوجد أطباء بعد.", en: "No doctors yet." },

  // patients
  addPatient: { ar: "تسجيل مريض", en: "Register patient" },
  patientName: { ar: "اسم المريض", en: "Patient name" },
  age: { ar: "العمر", en: "Age" },
  phone: { ar: "رقم الهاتف", en: "Phone" },
  phoneNumber: { ar: "رقم الهاتف", en: "Phone number" },
  patients: { ar: "المرضى", en: "Patients" },
  noPatientsYet: { ar: "لا يوجد مرضى مسجّلون بعد.", en: "No patients registered yet." },

  // chat
  chatModeGeneral: { ar: "عامة", en: "General" },
  chatModeTriage: { ar: "طارئة", en: "Urgent" },
  freeAlways: { ar: "الطوارئ مجانية دومًا", en: "Urgent care — always free" },
  typeMessage: { ar: "اكتب سؤالك هنا…", en: "Type your question…" },
  send: { ar: "إرسال", en: "Send" },
  sending: { ar: "…", en: "…" },
  newConversation: { ar: "محادثة جديدة", en: "New conversation" },
  chatHistory: { ar: "سجل المحادثات", en: "Chat history" },
  noSessionsYet: { ar: "لا توجد محادثات سابقة بعد.", en: "No past conversations yet." },
  source: { ar: "المصدر", en: "Source" },
  page: { ar: "صفحة", en: "page" },

  // appointments
  bookAppointment: { ar: "احجز موعد", en: "Book appointment" },
  book: { ar: "احجز", en: "Book" },
  booked: { ar: "تم الحجز", en: "Booked" },
  cancel: { ar: "إلغاء", en: "Cancel" },
  cancelled: { ar: "ملغى", en: "Cancelled" },
  slotDateTime: { ar: "الموعد", en: "Date & time" },
  yourAppointments: { ar: "مواعيدك", en: "Your appointments" },
  noAppointmentsYet: { ar: "لا توجد مواعيد بعد.", en: "No appointments yet." },
  status: { ar: "الحالة", en: "Status" },

  // records
  noRecordsYet: { ar: "لا توجد سجلات طبية بعد.", en: "No medical records yet." },
  fromClinicRecord: { ar: "من ملفك الطبي في العيادة", en: "From your clinic medical record" },

  // misc
  loading: { ar: "جارٍ التحميل…", en: "Loading…" },
  error: { ar: "حدث خطأ", en: "Something went wrong" },
  retry: { ar: "أعد المحاولة", en: "Retry" },
  save: { ar: "حفظ", en: "Save" },
  cancelAction: { ar: "إلغاء", en: "Cancel" },
  supportDisclaimer: {
    ar: "طبيبك أداة مساعدة تدعم علاقتك بطبيبك، ولا تحل محل زيارته.",
    en: "Tabeebak is a support tool for your relationship with your doctor, not a replacement for visiting them.",
  },

  // doctor dashboard
  doctorPanel: { ar: "لوحة الطبيب", en: "Doctor panel" },
  myPatients: { ar: "مرضاي", en: "My patients" },
  appointmentsWithMe: { ar: "المواعيد معي", en: "Appointments with me" },
  availability: { ar: "أوقات التوفر", en: "Availability" },
  addWindow: { ar: "إضافة وقت", en: "Add window" },
  dayOfWeek: { ar: "اليوم", en: "Day" },
  startTime: { ar: "من الساعة", en: "Start time" },
  endTime: { ar: "إلى الساعة", en: "End time" },
  noAvailabilityYet: { ar: "لم تحدد أوقات توفر بعد.", en: "No availability windows set yet." },
  daySun: { ar: "الأحد", en: "Sunday" },
  dayMon: { ar: "الاثنين", en: "Monday" },
  dayTue: { ar: "الثلاثاء", en: "Tuesday" },
  dayWed: { ar: "الأربعاء", en: "Wednesday" },
  dayThu: { ar: "الخميس", en: "Thursday" },
  dayFri: { ar: "الجمعة", en: "Friday" },
  daySat: { ar: "السبت", en: "Saturday" },
  medicalHistory: { ar: "السجل الطبي", en: "Medical history" },
  viewHistory: { ar: "عرض السجل", en: "View history" },
  addRecord: { ar: "إضافة سجل", en: "Add record" },
  diagnosis: { ar: "التشخيص", en: "Diagnosis" },
  notes: { ar: "ملاحظات", en: "Notes" },
  backToPatients: { ar: "الرجوع للمرضى", en: "Back to patients" },
  initialPasswordNotice: {
    ar: "شارك كلمة المرور دي مباشرة — هيغيّرها في أول تسجيل دخول.",
    en: "Share this password with them directly — they'll be asked to change it on first login.",
  },
  clinicLink: { ar: "رابط العيادة", en: "Clinic link" },

  // admin analytics
  analytics: { ar: "الإحصائيات", en: "Analytics" },
  totalDoctors: { ar: "عدد الأطباء", en: "Total doctors" },
  totalPatients: { ar: "عدد المرضى", en: "Total patients" },
  patientsPerDoctor: { ar: "المرضى لكل طبيب", en: "Patients per doctor" },
  doctorEmail: { ar: "البريد الإلكتروني للطبيب", en: "Doctor email" },

  // change password (forced, first login)
  changePassword: { ar: "تغيير كلمة المرور", en: "Change password" },
  mustChangePasswordNotice: {
    ar: "دي أول مرة تسجّل دخول — لازم تغيّر كلمة المرور المؤقتة قبل ما تكمل.",
    en: "This is your first login — you need to set your own password before continuing.",
  },
  newPassword: { ar: "كلمة المرور الجديدة", en: "New password" },
  confirmPassword: { ar: "تأكيد كلمة المرور", en: "Confirm password" },
  passwordMismatch: { ar: "كلمتا المرور غير متطابقتين", en: "Passwords don't match" },
  continueAction: { ar: "متابعة", en: "Continue" },

  // patient onboarding / welcome
  welcomeTitle: { ar: "أهلًا بيك في طبيبك", en: "Welcome to Tabeebak" },
  welcomeAskQuestion: { ar: "اسأل عن حالتك الصحية", en: "Ask a question about your condition" },
  welcomeBookAppointment: { ar: "احجز موعد مع طبيبك", en: "Book an appointment with your doctor" },
  welcomeSeeHistory: { ar: "شوف أدويتك وسجلك الطبي", en: "See your medications and medical history" },
  welcomeSafety: {
    ar: "طبيبك بيساعدك تفهم، ومش بديل عن طبيبك. في حالة الطوارئ، تواصل مع العيادة فورًا.",
    en: "Tabeebak helps you understand — it is not a replacement for your doctor. In an emergency, contact the clinic immediately.",
  },
  confirmYourInfo: { ar: "أكّد بياناتك", en: "Confirm your info" },
  getStarted: { ar: "ابدأ", en: "Get started" },

  // clinic-slug patient entry
  clinicNotFound: { ar: "العيادة غير موجودة", en: "Clinic not found" },
  wrongClinicError: {
    ar: "هذا الحساب لا يخص هذه العيادة.",
    en: "This account doesn't belong to this clinic.",
  },

  // shell / roles / chrome
  menu: { ar: "القائمة", en: "Menu" },
  close: { ar: "إغلاق", en: "Close" },
  evidenceWorkspace: { ar: "مساحة الأدلة السريرية", en: "Clinical evidence workspace" },
  verifiedKnowledge: { ar: "معرفة موثقة من العيادة", en: "Verified clinic knowledge" },
  clinicalSafe: { ar: "ضوابط السلامة مفعّلة", en: "Safety checks active" },
  rolePatient: { ar: "مريض", en: "Patient" },
  roleDoctor: { ar: "طبيب", en: "Doctor" },
  roleAdmin: { ar: "موظف الاستقبال", en: "Receptionist" },
  roleIt: { ar: "الدعم الفني", en: "IT" },
  loginSubtitle: { ar: "المساعد المعرفي لعيادتك", en: "The knowledge assistant for your clinic" },

  // chat empty state
  chatEmptyTitle: { ar: "كيف أقدر أساعدك؟", en: "How can I help you today?" },
  chatEmptyHint: {
    ar: "اسأل عن حالتك الصحية أو اطّلع على مواعيدك.",
    en: "Ask a health question, or check your appointments.",
  },
  patientAssistantTitle: { ar: "مساعد المواعيد", en: "Appointment assistant" },
  patientAssistantHint: {
    ar: "تحقق من مواعيدك أو احجز أو ألغِ أو أعد جدولة موعد.",
    en: "Check, book, cancel, or reschedule your appointments.",
  },
  patientAssistantThinking: { ar: "جارٍ التحقق من طلبك…", en: "Checking your request…" },
  recommendation: { ar: "التوصية", en: "Recommendation" },
  supportingEvidence: { ar: "الأدلة الداعمة", en: "Supporting evidence" },
  citations: { ar: "المراجع", en: "Citations" },
  evidenceStrength: { ar: "قوة الأدلة", en: "Evidence strength" },
  highEvidence: { ar: "أدلة قوية", en: "High evidence" },
  mediumEvidence: { ar: "أدلة متوسطة", en: "Medium evidence" },
  lowEvidence: { ar: "أدلة محدودة", en: "Low evidence" },
  insufficientEvidence: { ar: "أدلة غير كافية", en: "Insufficient evidence" },
  safetyAndLimits: { ar: "السلامة والحدود", en: "Safety & limits" },
  evidenceAudit: { ar: "تفاصيل تدقيق الأدلة", en: "Evidence audit details" },
  showEvidence: { ar: "عرض تفاصيل الأدلة", en: "Show evidence details" },
  hideEvidence: { ar: "إخفاء تفاصيل الأدلة", en: "Hide evidence details" },
  checkedSources: { ar: "المصادر التي تمت مراجعتها", en: "Sources checked" },
  missingEvidence: { ar: "الأدلة المفقودة", en: "Missing evidence" },
  verificationPassed: { ar: "تم التحقق من دعم الادعاءات", en: "Claim support verified" },
  exactExcerpt: { ar: "المقتطف الداعم", en: "Supporting excerpt" },
  vectorDistance: { ar: "مسافة البحث", en: "Vector distance" },
  rerankScore: { ar: "درجة إعادة الترتيب", en: "Rerank score" },
  chunkId: { ar: "معرّف المقطع", en: "Chunk ID" },
  openSource: { ar: "فتح المصدر", en: "Open source" },
  assistantThinking: { ar: "جارٍ البحث والتحقق من الأدلة…", en: "Retrieving and verifying evidence…" },
  evidenceFirstTitle: { ar: "إجابات صحية يمكن تتبعها", en: "Traceable answers from your clinic" },
  evidenceFirstHint: { ar: "كل ادعاء طبي مرتبط بمقتطف ومصدر تم التحقق منه.", en: "Every medical claim is mapped to a verified source excerpt." },

  // evaluation
  ragQuality: { ar: "جودة نظام الاسترجاع", en: "RAG quality" },
  evaluationSubtitle: { ar: "مقاييس الاسترجاع والأدلة والسلامة لأحدث تشغيل.", en: "Retrieval, evidence, safety, and latency from the latest evaluation run." },
  groundedAnswers: { ar: "إجابات موثقة", en: "Grounded answers" },
  citationValidity: { ar: "صلاحية المراجع", en: "Citation validity" },
  faithfulness: { ar: "الالتزام بالأدلة", en: "Faithfulness" },
  abstentionAccuracy: { ar: "رفض خارج النطاق", en: "Out-of-scope abstention" },
  recallAtFive: { ar: "الاستدعاء عند 5", en: "Recall@5" },
  contextPrecision: { ar: "دقة السياق", en: "Context precision" },
  latencyP95: { ar: "زمن P95", en: "P95 latency" },
  latestRun: { ar: "أحدث تشغيل", en: "Latest run" },
  evaluationUnavailable: { ar: "لا يوجد تقرير تقييم متاح بعد.", en: "No evaluation report is available yet." },
  pipelineHealth: { ar: "صحة خط الأنابيب", en: "Pipeline health" },
  modelAndPrompt: { ar: "النموذج والإعداد", en: "Model & prompt" },
  reportFailures: { ar: "حالات تحتاج مراجعة", en: "Cases requiring review" },

  // source trust
  trustedLibrary: { ar: "مكتبة المصادر الموثوقة", en: "Trusted source library" },
  trustedLibraryHint: { ar: "ارفع إرشادات موثوقة وراجع جودة الاستخراج قبل إتاحتها للمرضى.", en: "Upload trusted guidance and review extraction quality before making it available to patients." },
  sourceUrl: { ar: "رابط المصدر", en: "Source URL" },
  topic: { ar: "الموضوع", en: "Topic" },
  trustReview: { ar: "مراجعة الثقة", en: "Trust review" },
  extractionQuality: { ar: "جودة الاستخراج", en: "Extraction quality" },
  verifiedByDoctor: { ar: "تم التحقق بواسطة طبيب", en: "Verified by a doctor" },

  // clinic owner (contact only, not a login)
  clinicOwner: { ar: "مالك العيادة", en: "Clinic owner" },
  ownerName: { ar: "اسم المالك", en: "Owner name" },
  ownerPhone: { ar: "هاتف المالك", en: "Owner phone" },
  ownerEmail: { ar: "بريد المالك", en: "Owner email" },
  ownerContactHint: {
    ar: "بيانات تواصل فقط — المالك ليس له حساب دخول.",
    en: "Contact details only — the owner has no login account.",
  },

  // receptionist — patient registration with doctor assignment
  assignDoctor: { ar: "الطبيب المعالج", en: "Assigned doctor" },
  selectDoctor: { ar: "اختر الطبيب", en: "Select a doctor" },
  registerFirstDoctor: {
    ar: "سجّل طبيبًا واحدًا على الأقل قبل تسجيل المرضى.",
    en: "Register at least one doctor before registering patients.",
  },
  patientRegistered: { ar: "تم تسجيل المريض", en: "Patient registered" },

  // doctor — assistant chat
  assistant: { ar: "المساعد السريري", en: "Clinical assistant" },
  doctorAssistantHint: {
    ar: "اسأل إرشادات عيادتك الموثقة بلغة سريرية دقيقة.",
    en: "Ask your clinic's verified guidelines in precise clinical terms.",
  },

  // doctor — report a document issue to IT
  reportIssue: { ar: "الإبلاغ عن مشكلة", en: "Report an issue" },
  reportIssueHint: {
    ar: "صف المشكلة في هذا المستند وسيتحقق فريق الدعم من خط المعالجة.",
    en: "Describe the problem with this document; IT will investigate the pipeline.",
  },
  issueDescription: { ar: "وصف المشكلة", en: "Describe the issue" },
  submitReport: { ar: "إرسال البلاغ", en: "Submit report" },
  reportSubmitted: { ar: "تم إرسال البلاغ إلى الدعم الفني.", en: "Report sent to IT." },

  // IT dashboard
  itPanel: { ar: "لوحة الدعم الفني", en: "IT panel" },
  itOperations: { ar: "عمليات خط المعالجة", en: "Pipeline operations" },
  overview: { ar: "نظرة عامة", en: "Overview" },
  chatbot: { ar: "روبوت المحادثة", en: "Chatbot" },
  testPipeline: { ar: "اختبار", en: "Test" },
  bugReports: { ar: "البلاغات", en: "Reports" },
  crossClinicStats: { ar: "إحصائيات كل العيادات", en: "Cross-clinic statistics" },
  crossClinicHint: {
    ar: "أعداد إجمالية لكل العيادات للمراقبة — بدون أي بيانات مرضى.",
    en: "Aggregate counts across every clinic for monitoring — no patient data.",
  },
  clinic: { ar: "العيادة", en: "Clinic" },
  doctorCount: { ar: "الأطباء", en: "Doctors" },
  patientCount: { ar: "المرضى", en: "Patients" },
  documentCount: { ar: "المستندات", en: "Documents" },
  totalClinics: { ar: "عدد العيادات", en: "Total clinics" },
  ragMetricsTitle: { ar: "مقاييس جودة الاسترجاع", en: "Retrieval quality metrics" },
  ragMetricsHint: {
    ar: "أحدث تشغيل مرجعي لنظام الاسترجاع على مستوى النظام.",
    en: "The latest system-wide RAG benchmark run.",
  },
  pipelineTestTitle: { ar: "اختبار خط المعالجة", en: "Pipeline test" },
  pipelineTestHint: {
    ar: "شغّل مستندًا خطوة بخطوة مع سؤال اختباري لتشخيص مشكلة أبلغ عنها طبيب.",
    en: "Run a document stage by stage with a test question to diagnose a doctor's report.",
  },
  documentId: { ar: "معرّف المستند", en: "Document ID" },
  testQuestion: { ar: "سؤال الاختبار", en: "Test question" },
  runTest: { ar: "تشغيل الاختبار", en: "Run test" },
  running: { ar: "جارٍ التشغيل…", en: "Running…" },
  stageIndexing: { ar: "الفهرسة", en: "Indexing" },
  stageRetrieval: { ar: "الاسترجاع", en: "Retrieval" },
  stageGeneration: { ar: "التوليد", en: "Generation" },
  finalOutput: { ar: "المخرجات النهائية", en: "Final output" },
  stagePassed: { ar: "نجحت", en: "Passed" },
  stageFailed: { ar: "فشلت", en: "Failed" },
  stageNotReached: { ar: "لم تُنفّذ", en: "Not reached" },
  langsmithTraceTitle: { ar: "التتبّع في LangSmith", en: "Trace in LangSmith" },
  langsmithLink: { ar: "فتح في LangSmith", en: "Open in LangSmith" },
  langsmithNotConfigured: {
    ar: "تتبّع LangSmith غير مُفعّل في هذا النظام.",
    en: "LangSmith tracing is not configured for this system.",
  },
  langsmithConfiguredHint: {
    ar: "تتبّع هذا التشغيل جاهز — افتحه لرؤية كل مكالمة نموذج وعدد الرموز والزمن.",
    en: "The trace for this run is ready — open it to see every model call, token count, and latency.",
  },
  signalChain: { ar: "سلسلة المعالجة", en: "Signal chain" },
  stageInspector: { ar: "فحص المرحلة", en: "Stage inspector" },
  stageNotReachedHint: {
    ar: "لم تُنفّذ هذه المرحلة لأن مرحلة سابقة فشلت.",
    en: "This stage never ran because an earlier stage failed.",
  },
  hits: { ar: "نتيجة", en: "hits" },
  vectors: { ar: "المتجهات", en: "Vectors" },
  charCount: { ar: "عدد الأحرف", en: "Characters" },
  sampleChunks: { ar: "عيّنة من المقاطع", en: "Sample chunks" },
  retrievedChunks: { ar: "المقاطع المسترجعة", en: "Retrieved chunks" },
  documentUnverifiedTitle: { ar: "المستند غير معتمد بعد", en: "Document not verified yet" },
  documentUnverifiedHint: {
    ar: "هذا الاختبار يعمل داخل فهرس مؤقّت معزول، لذا نجاحه لا يعني وصول الإجابة للمرضى. يجب أن يعتمد الطبيب المستند أولًا قبل أن يُستخدم في الإجابة على أسئلة المرضى.",
    en: "This test runs against an isolated, temporary index, so passing here doesn't mean patients can see it. A doctor must mark the document verified before it can answer a patient question.",
  },
  verdictHealthyTitle: { ar: "خط المعالجة سليم", en: "Pipeline healthy" },
  verdictHealthyText: { ar: "اكتملت كل المراحل وتم توليد إجابة موثّقة بالمراجع.", en: "Every stage passed and a grounded, cited answer was generated." },
  verdictFailedTitle: { ar: "توقّفت السلسلة عند مرحلة", en: "The chain stopped at a stage" },
  verdictUngroundedTitle: { ar: "لا توجد أدلة كافية للإجابة", en: "Not enough evidence to answer" },
  verdictUngroundedText: {
    ar: "اكتمل الاسترجاع لكن التوليد رفض الإجابة لعدم كفاية الأدلة الداعمة.",
    en: "Retrieval completed, but generation refused to answer because the retrieved evidence didn't support it.",
  },
  bugReportsQueue: { ar: "قائمة بلاغات الأطباء", en: "Doctor bug-report queue" },
  noBugReports: { ar: "لا توجد بلاغات.", en: "No reports." },
  statusOpen: { ar: "مفتوح", en: "Open" },
  statusInvestigating: { ar: "قيد الفحص", en: "Investigating" },
  statusResolved: { ar: "تم الحل", en: "Resolved" },
  markInvestigating: { ar: "بدء الفحص", en: "Start investigating" },
  markResolved: { ar: "تم الحل", en: "Mark resolved" },
  investigate: { ar: "افحص", en: "Investigate" },
  reportedOn: { ar: "أُبلغ في", en: "Reported" },
} as const;

export type DictKey = keyof typeof dict;
export type Lang = "ar" | "en";

interface LangContextValue {
  lang: Lang;
  dir: "rtl" | "ltr";
  setLang: (lang: Lang) => void;
  toggleLang: () => void;
  t: (key: DictKey) => string;
}

const LangContext = createContext<LangContextValue | null>(null);

const STORAGE_KEY = "tabibak-lang";

export function LangProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState<Lang>("en");

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (stored === "ar" || stored === "en") setLangState(stored);
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  const setLang = (next: Lang) => {
    setLangState(next);
    window.localStorage.setItem(STORAGE_KEY, next);
  };

  const dir = lang === "ar" ? "rtl" : "ltr";

  useEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.dir = dir;
  }, [lang, dir]);

  const t = (key: DictKey) => dict[key][lang];

  return (
    <LangContext.Provider
      value={{ lang, dir, setLang, toggleLang: () => setLang(lang === "ar" ? "en" : "ar"), t }}
    >
      {children}
    </LangContext.Provider>
  );
}

export function useLang() {
  const ctx = useContext(LangContext);
  if (!ctx) throw new Error("useLang() must be used inside <LangProvider>");
  return ctx;
}

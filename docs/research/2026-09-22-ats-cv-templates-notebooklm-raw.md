# NotebookLM synthesis (raw) — CV-ATS — ATS-friendly resume standard (1bc6f53c-08bf-4cec-b2b3-fa69fff09fd8)

Fetched 2026-09-22 with `notebooklm ask`. Bracketed numbers are NotebookLM citation indices into the source list below, not page numbers.

## Sources

- 3 ATS-friendly resume templates & how to choose yours - CandyCV — https://www.candycv.com/comparisons/ats-friendly-resume-templates-3-examples-that-work-and-which-one-to-choose-5
- ATS Can't Read Tables in Resume: 5 Fixes and Workarounds for AI ResumeMaker — https://www.resumemakeroffer.com/en/blog/post/95001
- ATS friendly resume: PDF or Word? (2026 guide to Workday, Taleo & ATS parsers) | Blog — https://jobsparrow.ai/blog/ats-friendly-resume-pdf-or-word-2026-guide-to-workday-taleo-ats-parsers-
- Are LaTeX Resumes ATS-Friendly? The Two Traps and the Fix - ATS Verification — https://atsverification.com/blog/latex-resume-ats-friendly/
- Best ATS Resume Templates 2026: 8 Free Downloads That Pass Every Parser — https://resumeoptimizerpro.com/blog/best-ats-friendly-resume-templates-2026
- Free ATS Resume Template 2026: Download and Pass Scanners | ResumeAdapter — https://www.resumeadapter.com/blog/ats-resume-template-free
- Handout 4 - Harvard Resume Examples.pdf - American Political Science Association (APSA) — https://apsanet.org/Portals/54/web/Handout%204%20-%20Harvard%20Resume%20Examples.pdf?ver=BQ3JG_ifefqqOOsrYio64A%3D%3D&timestamp=1653587429108
- Harvard College Bullet Point Resume Template - Mignone Center for Career Success — https://careerservices.fas.harvard.edu/resources/bullet-point-resume-template/
- Harvard Resume Template — Free Word & PDF, ATS-Friendly | CVEdge — https://www.thecvedge.com/resume-templates/ats-friendly/harvard-cv
- Harvard Resume Template: Exact Format, Fonts, and ATS Verdict — https://resumeoptimizerpro.com/blog/harvard-resume-template
- Harvard Resume Template: Free Download & Complete Guide (2026) - StylingCV — https://stylingcv.com/resume-templates/harvard-resume-template/
- Harvard Resume Template: Free Download + Bullet Formula (2026) - Careerkit.me — https://www.careerkit.me/blog/harvard-college-bullet-point-resume-template-a-comprehensive-guide
- How Resume Parsers Actually Work: Inside Workday, Greenhouse, Lever, iCIMS, Taleo — https://resumeoptimizerpro.com/blog/how-resume-parsers-actually-work
- How the Workday ATS Reads Your Resume (2026) | ResumeAdapter — https://www.resumeadapter.com/ats/workday/how-it-parses
- I Reverse-Engineered How 5 ATS Systems Read Your Resume - Jobloo — https://jobloo.co/blog/how-ats-systems-read-your-resume/
- I am creating a Resume using a Resume Template. However, the text keeps jumping on to another page. - Google Docs Editors Community — https://support.google.com/docs/thread/415775955/i-am-creating-a-resume-using-a-resume-template-however-the-text-keeps-jumping-on-to-another-page?hl=en
- Jake's Resume - Overleaf, Online LaTeX Editor — https://www.overleaf.com/latex/templates/jakes-resume/syzfjbzwjncs
- Jake's Resume LaTex Template (Overleaf)- Help needed with changing font - Reddit — https://www.reddit.com/r/LaTeX/comments/1h4zgf0/jakes_resume_latex_template_overleaf_help_needed/
- Jake's Resume Template (ATS-Friendly) - ResuMax — https://resumax.ai/resume-templates/jakes-resume
- Jake's Resume Template - Free PDF Download & LaTeX Code — https://www.sweresume.app/articles/jakes-resume/
- Jake's Resume vs. Overleaf: Do You Actually Need LaTeX? | Rejectless — https://www.rejectless.app/guides/jakes-resume-vs-overleaf
- Jake's Resume: How to Build the Ultimate Tech Resume in LaTeX (Without Code) - Lampzi — https://lampzi.com/blogs/jakes-resume-no-code
- LaTeX Resume Template: Best Options, ATS Risks, and When to Use One — https://resumeoptimizerpro.com/blog/latex-resume-template
- Resume Scanner - Get a Free ATS Resume Scan - Resume Worded — https://resumeworded.com/resume-scanner
- Resume/CV/Cover Letter Templates – Harvard FAS | Mignone Center for Career Success — https://careerservices.fas.harvard.edu/resources/category/resume-cv-cover-letter-templates/
- Standardized Specifications for ATS-Friendly Resume Engineering in 2026: Technical Parsing Architectures, Platform Quirks, and Template Performance — 
- Workday vs Greenhouse vs Lever ATS Parsing Compared (2026) - HireFlow's ATS checker — https://hireflow.net/blog/workday-vs-greenhouse-vs-lever-which-parses-best
- https://tex.stackexchange.com/questions/651853/how-to-modify-jakes-resume-template-for-chinese-characters — https://tex.stackexchange.com/questions/651853/how-to-modify-jakes-resume-template-for-chinese-characters
- https://www.jobscan.co/resume-builder — https://www.jobscan.co/resume-builder
- https://www.jobscan.co/resume-templates — https://www.jobscan.co/resume-templates
- https://www.jobscan.co/resume-templates/ats-templates — https://www.jobscan.co/resume-templates/ats-templates
- https://www.jobscan.co/resume-templates/modern-resume-templates — https://www.jobscan.co/resume-templates/modern-resume-templates
- iCIMS vs Taleo 2026: Resume Fixes That Stop Auto-Rejects - KINETK — https://kinetk.io/blog/icims-taleo-mistakes/

## Answer

Answer:
Here are the ATS-safe specifications, section orders, and formatting rules for 
the three major resume formats, along with the universal ATS parsing 
requirements that apply across all templates.

---

### **Universal ATS Rules (Applies to All Templates)**

* **Section Headings**: Use exact, standard, whitelisted heading names that ATS 
Stage 3 section segmenters recognize: `WORK EXPERIENCE`, `PROFESSIONAL 
EXPERIENCE`, `EDUCATION`, `SKILLS`, `TECHNICAL SKILLS`, `PROFESSIONAL SUMMARY`, 
and `CERTIFICATIONS` [1-4]. Creative headings (e.g., *"My Journey"*, 
*"Toolkit"*, *"Where I've Been"*) fail regex lookups and classifiers, causing 
the parser to drop or misfile the entire section [1, 3-6].
* **Date Formatting**: Use a single, consistent date format throughout the 
entire document: `Month YYYY – Month YYYY` (e.g., `January 2024 – Present`) or 
`MM/YYYY – MM/YYYY` [1, 3, 7-10]. Active positions **must** use the exact word 
`Present` (avoid "Current" or "Ongoing") [10-12]. Avoid non-standard or 
irregular abbreviations (e.g., "Mar. 2022" or "Jan '22"), which break regex date
taggers in Workday and Taleo [13, 14]. Position dates on the same line as the 
job title/employer using right-aligned tab stops rather than table rows [10, 15,
16].
* **Contact Block**: Place contact details (Full Name, City/State or 
City/Country, Phone, Email, LinkedIn/GitHub URL) as selectable plain text at the
**very top of the main document body** [1-3, 11, 17]. **Never place contact 
details inside Word/PDF page headers or footers**, as Stage 1 extractors strip 
or ignore header/footer XML layers, causing applications to register without 
phone numbers or emails [1, 3, 11, 18-20]. Do **not** include headshots/photos, 
full street addresses, or icon fonts (e.g., FontAwesome glyphs/symbols), which 
extract as unmapped garbage characters that corrupt contact fields [21-24]. For 
non-US candidates applying to US remote roles, explicitly list work 
authorization (e.g., *"Authorized to work in the US / No visa sponsorship 
required"*) in the header block to pass initial location filters.
* **Layout Constraints (No Tables, Columns, or Headers/Footers)**: Strictly use 
a **single-column layout** [1, 3, 9, 18, 25-28]. Multi-column designs cause 
positional PDF extractors (like Apache Tika) to read horizontally across the 
page, interleaving column text into garbled word soup (~34% parse failure rate 
for columns, ~31% for tables, vs. 4% for single-column DOCX) [26, 28-30]. Tables
disrupt linear reading order, while floating text boxes and page headers/footers
live in separate XML nodes that parsers skip entirely [1, 3, 18, 20, 30-32].
* **File Format (PDF vs. DOCX)**:
  * **Microsoft Word (.docx)**: Recommended for enterprise corporate portals 
(Workday, Taleo, iCIMS). OpenXML provides lossless tree parsing, achieving the 
highest section extraction accuracy (~97–98%) [1, 9, 33-37].
  * **Text-Based PDF (.pdf)**: Preferred for modern tech ATS (Greenhouse, Lever,
Ashby) or direct email submissions, provided it is exported directly from Word, 
Google Docs, or compiled via `pdflatex` [1, 9, 38-40]. **Never** submit graphic 
design exports (Canva, Figma, InDesign) or scanned PDFs, which export text as 
vector shapes or flattened images, resulting in a blank parse [1, 18, 22, 
39-41].

---

### **Template A: Hybrid / Combination Resume**

Best for career changers, non-linear career paths, mid-career professionals with
diverse skill sets, or candidates wanting skills prioritized up front while 
maintaining a full chronological history [19, 42-46].

#### **1. Exact Section Order & Headings**
1. **Header / Contact Information** [2, 17]
2. `PROFESSIONAL SUMMARY` (or `SUMMARY`) [1, 2, 17]
3. `CORE SKILLS` (or `TECHNICAL SKILLS` / `CORE COMPETENCIES`) [1, 2, 4, 17, 45]
4. `WORK EXPERIENCE` (or `PROFESSIONAL EXPERIENCE`) [1, 2, 4, 17]
5. `EDUCATION` [1, 2, 4, 17]
6. `CERTIFICATIONS` *(optional)* [1, 2, 4, 17]

#### **2. What Goes in Each Section**
* **Header**: Candidate Name, Location (`City, State` or `City, Country`), 
Phone, Professional Email, LinkedIn URL, and Work Authorization line [2, 17, 
23].
* **Professional Summary**: 2 to 4 sentences containing target job title, total 
years of experience, core hard skills, and 1 high-level quantified achievement 
[2, 17, 23, 45].
* **Core Skills**: Grouped, comma-separated lists of technical skills, software,
tools, and domain areas placed *before* work history so skills-based ATS filters
capture them immediately [2, 3, 17, 45, 47].
* **Work Experience**: Reverse-chronological entries (Company, Job Title, 
City/State, Dates) with bullet points connecting listed skills to measurable 
business impact [2, 17, 45, 48].
* **Education**: Degree name, major, institution, graduation year [2, 17].
* **Certifications**: Official title, issuing body, year obtained [2, 17].

#### **3. Bullet Style & Metric Formula**
* Follow the **STAR / Google XYZ formula**: `[Action Verb] + [Task/Scope] + 
[Quantified Metric] + [Business Impact/Context]` [17, 49, 50].
* Keep bullets to **1 to 2 lines maximum** [51]. Quantify at least 60% of 
bullets with metrics (%, \$, scale) [17, 52, 53].
* Strictly **no personal pronouns** ("I", "we", "my") [52].

#### **4. Recommended Page Length**
* **1 page** for 0–10 years of experience [9, 54, 55].
* **2 pages** for 10+ years of experience [9, 54-56].

#### **5. What to Avoid**
* Do **not** use purely functional resume structures that omit dated job 
entries; ATS filters specifically penalize or auto-reject resumes lacking clear 
employment dates [9, 44, 57].
* Avoid placing skills inside multi-column sidebars or floating text boxes [1, 
22].

---

### **Template B: Technical / Engineering (AI / Software) Resume**

Best for software engineers, AI engineers, developers, CS graduates, and tech 
professionals (e.g., Jake's Resume structure) [58-63].

#### **1. Exact Section Order & Headings**
* **Option 1 (Mid / Senior Profile — 3+ years experience)**:
  1. **Header / Contact Information** [17, 64, 65]
  2. `PROFESSIONAL SUMMARY` *(optional)* [1, 2, 17]
  3. `TECHNICAL SKILLS` (or `SKILLS`) [1, 3, 4, 64, 65]
  4. `WORK EXPERIENCE` (or `PROFESSIONAL EXPERIENCE`) [1, 3, 4, 64, 65]
  5. `PROJECTS` (or `TECHNICAL PROJECTS`) [64, 65]
  6. `EDUCATION` [1, 4, 64, 65]
* **Option 2 (Students / New Grads — Canonical Jake's Resume Order)**:
  1. **Header / Contact Information** [64, 65]
  2. `EDUCATION` [64, 65]
  3. `EXPERIENCE` (or `WORK EXPERIENCE`) [64, 65]
  4. `PROJECTS` [64, 65]
  5. `TECHNICAL SKILLS` [64, 65]

#### **2. What Goes in Each Section**
* **Header**: Name, Phone, Email, LinkedIn URL, GitHub / Portfolio URL, and Work
Authorization line [17, 64-66].
* **Technical Skills**: Plain-text grouped categories: `Languages`, 
`Frameworks`, `Cloud & Infrastructure`, `Developer Tools`, and `AI/ML 
Frameworks` [1, 64-66]. Dual-encode acronyms and full names (e.g., 
*"Retrieval-Augmented Generation (RAG)"*) [1, 47, 67].
* **Work Experience**: Company, Title, Location, Dates, and 3–5 bullets 
describing engineering architecture, infrastructure scale, and performance 
improvements [17, 51, 64-66].
* **Projects**: Project Name, inline tech stack (`Project Name | Tech Stack: 
Python, PyTorch, vLLM, Docker`), Dates, and 1–3 outcome-driven bullets [64, 
68-70].
* **Education**: Degree, Major, Institution, Graduation Year, optional GPA (if 
≥3.5) [17, 64, 65, 71].

#### **3. Bullet Style & Metric Formula**
* Lead every bullet with a strong technical action verb (*Architected, Deployed,
Fine-Tuned, Scaled, Optimized*) [66, 67, 70].
* Include technical context and metrics: e.g., *"Cut p99 API response latency by
42% and reduced GPU infrastructure spending by \$180K by deploying a fine-tuned 
model pipeline using vLLM."* [66, 67, 70, 72].
* 1 to 2 lines per bullet [51, 73]. Strictly no personal pronouns [52].

#### **4. Recommended Page Length**
* **1 page** for entry/mid-level candidates (under 10 years experience) [9, 54, 
74, 75].
* **2 pages** for senior/staff/principal engineers (10–15+ years experience) 
[56, 76, 77].

#### **5. What to Avoid**
* **LaTeX Technical Traps**: When compiling LaTeX templates (like Jake's Resume)
on Overleaf, unpatched TeX ligatures (`fi`, `fl`, `ff`) compile without 
ToUnicode maps, causing words like "Financial" to extract as `ﬁnancial` and 
breaking ATS keyword searches for "fi" [24, 38, 67, 78, 79]. Include preamble 
patches (`\pdfgentounicode=1`, `\usepackage{cmap}`, `\usepackage[T1]{fontenc}`) 
[38, 67, 68, 79].
* **Icon Font Trap**: Remove FontAwesome icons (`\faEnvelope`, `\faPhone`) in 
LaTeX contact headers; they extract as unmapped garbage characters that corrupt 
email/phone fields [21, 24, 79].
* Do **not** use visual skill rating bars or progress graphs (e.g., "Python: 
90%"), which are completely invisible to parsers [1, 80].

---

### **Template C: Leadership / Executive Resume**

Best for C-suite, VPs, Directors, Management Consulting (MBB), Investment 
Banking, and Senior Executive roles (e.g., Harvard OCS / Executive Signature 
template) [60, 81-87].

#### **1. Exact Section Order & Headings**
1. **Header / Contact Information** [17, 52, 88]
2. `EXECUTIVE SUMMARY` (or `PROFESSIONAL SUMMARY`) [1, 2, 86, 87]
3. `WORK EXPERIENCE` (or `PROFESSIONAL EXPERIENCE`) [1, 2, 4, 52, 88]
4. `BOARD POSITIONS` (or `ADVISORY ROLES`) *(if applicable)* [86, 87]
5. `EDUCATION` [1, 2, 4, 52, 88]
6. `SKILLS & INTERESTS` (or `ADDITIONAL INFORMATION`) [87, 89-91]

#### **2. What Goes in Each Section**
* **Header**: Name, Location (`City, State` or `City, Country`), Phone, 
Professional Email, LinkedIn URL, and Work Authorization line [52, 88].
* **Executive Summary**: 2 to 4 lines capturing organizational scope, total 
experience, P&L responsibility, team sizes managed, and high-level 
growth/transformation outcomes [2, 86, 87].
* **Work Experience**: Company Name, Job Title, Location, Dates, with 3–5 
bullets per role emphasizing revenue growth, cost optimization, P&L scale, team 
expansion, and strategic execution [52, 87, 88, 92].
* **Board Positions / Advisory Roles**: Formal board seats, governance 
committees, or advisory roles [86, 87].
* **Education**: Executive MBA/Master's/Bachelor's degrees, institutions, 
graduation dates, and notable academic honors [88, 90, 92].
* **Skills & Interests / Additional Information**: Categorized lines for 
Executive Skills, Board Governance, Languages, Certifications, and 1 short line 
of personal interests [89-91, 93].

#### **3. Bullet Style & Metric Formula**
* Open with executive leadership verbs (*Spearheaded, Orchestrated, Architected,
Transformed, Directed, Generated*) [52, 94, 95].
* Every bullet **must** contain high-level metrics: P&L dollar amounts, ARR, 
active users, cost reduction percentages, or team headcount [52, 53, 95].
* 1 to 2 lines per bullet [51]. Strictly no personal pronouns ("I", "we") [52].

#### **4. Recommended Page Length**
* **2 pages** is standard and expected for senior executives and professionals 
with 10–15+ years of experience [9, 54-56, 76, 77, 81, 86].
* Page 2 **must be substantially filled** (at least 50–75% of the page) [56, 
77].

#### **5. What to Avoid**
* Do **not** add photos, logos, colored accent bars, or decorative horizontal 
lines created via drawing tools (use Word's paragraph bottom border instead) 
[16, 52, 76, 96, 97].
* Avoid weak, passive openers like *"Responsible for managing..."* or *"Duties 
included..."* [52, 97-99].
* Do **not** leave contact details inside page headers or footers [16, 20, 100].

---

💡 *Would you like me to generate a copy-ready, single-column DOCX or LaTeX code
snippet pre-filled for any of these specific templates?*


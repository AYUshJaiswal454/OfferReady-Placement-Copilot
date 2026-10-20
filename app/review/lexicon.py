"""Word lists used by the review engine."""
from __future__ import annotations

import gzip
import re
from functools import lru_cache
from pathlib import Path

from ..skills import EXTRA_CASING, SKILLS

DATA = Path(__file__).resolve().parent.parent / "data"

ACTION_VERBS = set("""
accelerated achieved acquired adapted added addressed administered advanced advised advocated aggregated analysed analyzed
annotated applied architected arranged assembled assessed audited authored automated balanced benchmarked boosted
bootstrapped brainstormed budgeted built calculated captained catalogued centralized championed chaired channeled
clarified classified cleaned coached coded collaborated collected combined compiled completed composed computed conceived
conceptualized condensed conducted configured consolidated constructed consulted containerized contributed converted
coordinated co-founded cofounded crafted created curated customized cut debugged decreased defined delivered deployed
designed detected determined developed devised diagnosed digitized directed discovered dispatched documented doubled drafted
drove edited educated eliminated enabled encrypted engineered enhanced established evaluated exceeded executed expanded
expedited experimented explored extended extracted fabricated facilitated finalized fine-tuned fixed forecasted formalized
formulated fostered founded gathered generated grew guided halved handled headed hosted identified illustrated implemented
improved incorporated increased indexed influenced initiated innovated inspected installed instituted instructed integrated
interpreted interviewed introduced invented investigated launched led leveraged lifted localized maintained managed mapped
mastered maximized measured mentored merged migrated minimized mobilized modeled modelled modernized modified monitored
motivated navigated negotiated normalized onboarded operated optimised optimized orchestrated organised organized
outperformed overhauled oversaw parallelized parsed partnered performed persuaded piloted pioneered planned predicted
prepared presented prioritized produced profiled programmed promoted prototyped provisioned published qualified quantified
queried raised ranked rebuilt received recommended reconciled recruited redesigned reduced re-engineered refactored refined
regulated rehabilitated reinforced released remediated rendered reorganized replaced reported represented researched resolved
restructured retrieved revamped reviewed revised rewrote safeguarded saved scaled scheduled scoped scraped screened secured
segmented selected served set shipped showcased simplified simulated slashed solved spearheaded sped stabilized standardized
steered streamlined strengthened structured subscribed succeeded summarized supervised supported surpassed surveyed
synchronized synthesized systematized tackled taught tested tightened topped tracked trained transformed translated
transitioned trimmed tripled troubleshot tuned uncovered unified unlocked updated upgraded validated verified visualized
volunteered won wrote
""".split())

# Present-tense forms are fine for ongoing work ("Build", "Lead"): derive the base forms.
_PRESENT = set()
for _v in list(ACTION_VERBS):
    if _v.endswith("ied"):
        _PRESENT.add(_v[:-3] + "y")
    elif _v.endswith("ed"):
        _PRESENT.add(_v[:-2])
        _PRESENT.add(_v[:-1])
        if len(_v) > 4 and _v[-3] == _v[-4]:
            _PRESENT.add(_v[:-3])
ACTION_VERBS_ANY = ACTION_VERBS | _PRESENT | {
    "build", "builds", "lead", "leads", "write", "writes", "drive", "run", "ran", "make", "teach", "win", "grow",
    "develops", "designs", "creates", "implements", "manages", "maintains", "optimizes", "automates", "deploys",
    "architect", "ship", "build", "own", "owned", "sold", "spoke", "taught", "began", "chose", "drew", "flew",
}

WEAK_STARTERS = {
    "worked": "Worked on/with is passive. Lead with what you built or changed: \"Built\", \"Implemented\", \"Optimized\".",
    "working": "Lead with the result, not the activity: \"Built\", \"Implemented\".",
    "responsible": "\"Responsible for\" describes a duty, not an achievement. Say what you did: \"Managed\", \"Led\", \"Owned\".",
    "helped": "\"Helped\" hides your contribution. Name your part: \"Implemented\", \"Designed\", \"Fixed\".",
    "assisted": "\"Assisted\" hides your contribution. Name your part: \"Implemented\", \"Analyzed\".",
    "involved": "\"Involved in\" is vague. Say what you personally did.",
    "participated": "\"Participated in\" is vague. For competitions, state the result: \"Ranked\", \"Won\", \"Finished top 10%\".",
    "did": "\"Did\" is weak. Use a specific verb: \"Built\", \"Analyzed\", \"Automated\".",
    "made": "\"Made\" is generic. Prefer \"Built\", \"Designed\", \"Developed\".",
    "was": "Start with an action verb, not \"was\".",
    "tasked": "Start with what you achieved, not what you were asked to do.",
    "learned": "Learning is expected. Show what you built with it: \"Built X using Y\".",
    "learnt": "Learning is expected. Show what you built with it: \"Built X using Y\".",
    "familiar": "\"Familiar with\" signals low confidence. Show the skill through a project bullet instead.",
    "using": "Start with the verb, then the tool: \"Built X using Y\".",
    "the": "Start with an action verb, not an article.",
    "a": "Start with an action verb, not an article.",
    "an": "Start with an action verb, not an article.",
    "i": "Drop first-person pronouns; start with the action verb.",
    "my": "Drop first-person pronouns; start with the action verb.",
    "we": "Say what *you* did, not the team: start with your action verb.",
    "handled": "\"Handled\" is vague. Say how: \"Managed\", \"Resolved\", \"Processed\".",
    "got": "\"Got\" is informal. Use \"Earned\", \"Secured\", \"Achieved\".",
    "attended": "Attending is not an achievement. Mention what you learned or built there, or drop it.",
}

STRONG_VERB_SUGGESTIONS = {
    "build": ["Built", "Developed", "Engineered"],
    "improve": ["Optimized", "Improved", "Reduced"],
    "lead": ["Led", "Coordinated", "Spearheaded"],
    "analyze": ["Analyzed", "Modeled", "Forecasted"],
    "automate": ["Automated", "Streamlined"],
    "design": ["Designed", "Architected", "Prototyped"],
    "fix": ["Debugged", "Resolved", "Fixed"],
    "teach": ["Mentored", "Trained", "Taught"],
    "win": ["Won", "Ranked", "Secured"],
}

HEADINGS: dict[str, list[str]] = {
    "education": ["education", "academic background", "academics", "educational qualification", "educational qualifications",
                  "academic qualifications", "academic details", "education details", "scholastic achievements"],
    "experience": ["experience", "work experience", "professional experience", "internships", "internship",
                   "internship experience", "employment", "work history", "industrial experience", "industry experience",
                   "experience and internships", "relevant experience"],
    "projects": ["projects", "academic projects", "personal projects", "key projects", "project work", "technical projects",
                 "notable projects", "major projects", "selected projects", "project experience", "projects undertaken"],
    "skills": ["skills", "technical skills", "skills summary", "core competencies", "technologies", "tech stack", "tools",
               "technical proficiency", "key skills", "skills and tools", "technical skills and interests", "skill set",
               "skillset", "tools and technologies", "programming skills", "technical expertise"],
    "achievements": ["achievements", "accomplishments", "awards", "honors", "honours", "awards and achievements",
                     "achievements and awards", "honors and awards", "competitive programming", "awards and honors",
                     "scholastic achievements", "key achievements"],
    "cocurricular": ["extra curricular activities", "extracurricular activities", "extra-curricular activities",
                     "co-curricular activities", "co curricular activities", "cocurricular activities",
                     "positions of responsibility", "position of responsibility", "leadership", "volunteering",
                     "volunteer experience", "activities", "clubs", "leadership and activities", "extracurriculars",
                     "extra curricular", "extracurricular", "co-curricular", "leadership experience", "por"],
    "certifications": ["certifications", "certificates", "licenses and certifications", "courses", "online courses",
                       "certifications and courses", "trainings", "training", "courses and certifications"],
    "summary": ["summary", "profile", "objective", "career objective", "about me", "professional summary", "profile summary",
                "about", "personal statement"],
    "publications": ["publications", "research", "research papers", "papers"],
    "coursework": ["relevant coursework", "coursework", "subjects", "key courses"],
    "languages": ["languages", "languages known"],
    "interests": ["interests", "hobbies", "hobbies and interests", "interests and hobbies"],
    "contact": ["contact", "contact information", "personal details", "personal information"],
}
HEADING_LOOKUP = {variant: canonical for canonical, variants in HEADINGS.items() for variant in variants}

DISPLAY_HEADING = {
    "education": "Education", "experience": "Experience", "projects": "Projects", "skills": "Technical Skills",
    "achievements": "Achievements", "cocurricular": "Extra-Curricular Activities", "certifications": "Certifications",
    "summary": "Summary", "publications": "Publications", "coursework": "Relevant Coursework", "languages": "Languages",
    "interests": "Interests", "contact": "Contact",
}

MONTHS = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"

METRIC_RE = re.compile(
    r"(?:\b\d[\d,]*(?:\.\d+)?\s?(?:%|percent|x\b|×|\+|k\b|K\b|M\b|ms\b|milliseconds|sec\b|seconds|s\b|minutes|mins|hrs|hours|days|weeks"
    r"|users|students|customers|clients|downloads|installs|requests|rps|qps|tps|stars|members|participants|teams|people|"
    r"visitors|views|records|rows|images|documents|queries|transactions|lakh|lakhs|crore|cr\b|lpa|endpoints|apis|pages|"
    r"features|modules|bugs|tickets|issues|tests|commits|contributors|schools|colleges|cities|languages|models|accuracy|"
    r"f1|precision|recall|auc|rank|position)"
    r"|(?:₹|\$|rs\.?|inr|usd)\s?\d[\d,]*(?:\.\d+)?"
    r"|\btop\s?\d+%?|\brank(?:ed)?\s?#?\d+|\b\d+(?:st|nd|rd|th)\s(?:place|position|rank|prize)|\bair\s?\d+"
    r"|\b(?:reduced|increased|improved|boosted|cut|grew|saved|decreased|raised|lowered|accelerated|doubled|tripled|halved)\b[^.]{0,40}\d"
    r"|\b\d+(?:\.\d+)?\s?/\s?\d+\b)",
    re.I,
)
YEAR_ONLY_RE = re.compile(r"^(?:19|20)\d{2}$")

FIRST_PERSON_RE = re.compile(r"\b(I|me|my|mine|myself)\b")

# Proper nouns common on Indian student resumes (not in an English dictionary).
PROPER_NOUNS = set("""
india indian bengaluru bangalore hyderabad pune mumbai delhi noida gurugram gurgaon chennai kolkata ahmedabad jaipur
lucknow indore bhopal chandigarh kochi coimbatore nagpur patna ranchi bhubaneswar vizag visakhapatnam mysuru mysore
manipal vellore warangal surat vadodara thane navi kanpur varanasi dehradun guwahati mangalore udupi trichy tiruchirappalli
iit iiit nit bits vit srm kiit lpu amity manipal msot jee neet cbse icse isc hsc ssc aissce aisse gpa cgpa sgpa percentile
btech mtech bca mca bsc msc mba bba bcom diploma hackathon hackathons ideathon codathon sih gfg nptel coursera udemy
infosys tcs wipro accenture cognizant capgemini zoho flipkart swiggy zomato paytm razorpay cred meesho phonepe ola byju
byjus unacademy freshworks postman browserstack nykaa myntra dream11 groww zerodha upstox jio airtel mahindra tata
reliance amazon google microsoft meta adobe oracle samsung intel nvidia qualcomm deloitte kpmg pwc ey goldman sachs morgan
jpmorgan citi barclays hsbc walmart uber atlassian salesforce cisco ibm hackerearth hackerrank codechef codeforces leetcode
geeksforgeeks kaggle devfolio unstop internshala naukri wellfound angellist github gitlab bitbucket linkedin
""".split())

COMMON_RESUME_WORDS = set("""
api apis backend frontend fullstack microservices dataset datasets workflow workflows dashboard dashboards chatbot chatbots
webapp website websites app apps deployment deployments scalability latency throughput uptime frontend codebase codebases
repo repos github teammates hackathon hackathons onboarding stakeholder stakeholders realtime real-time e-commerce ecommerce
login signup authentication authorization middleware endpoint endpoints schema schemas database databases json csv
pipeline pipelines preprocessing tokenization embeddings embedding vectorization hyperparameter hyperparameters
classifier classifiers regression clustering inference chatgpt llm llms genai prompt prompts finetuning fine-tuning
dockerized containerized kubernetes serverless cloud saas analytics visualization visualizations ui ux figma wireframes
wireframe prototyping prototype prototypes mockups mockup responsive cross-platform multiplayer leaderboard leaderboards
gamified gamification blockchain crypto nft web3 iot arduino raspberry sensor sensors esp32 simulink matlab autocad
solidworks ansys pcb vlsi verilog fpga microcontroller embedded opencv yolo cnn rnn lstm bert gpt transformer transformers
scraper scraping crawler crawlers automation automations chrome extension plugin plugins npm pip cli gui sdk sdks
cgpa sgpa coursework semester semesters internship internships intern interns mentee mentees mentor mentors
""".split())


@lru_cache(maxsize=1)
def english_words() -> frozenset[str]:
    path = DATA / "words_en.txt.gz"
    words: set[str] = set()
    if path.exists():
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            words = {w.strip() for w in fh if w.strip()}
    lowered = {w.lower() for w in words}
    tech = set()
    for skill in SKILLS:
        for name in (skill.name, *skill.aliases, *skill.context_aliases):
            for part in re.split(r"[\s/]+", name.lower()):
                tech.add(part)
    tech |= {k.lower() for k in EXTRA_CASING} | {v.lower() for v in EXTRA_CASING.values()}
    present_forms = {p for p in ACTION_VERBS_ANY if p in lowered}
    return frozenset(lowered | tech | COMMON_RESUME_WORDS | PROPER_NOUNS | ACTION_VERBS | present_forms)


@lru_cache(maxsize=1)
def suggestion_vocab() -> frozenset[str]:
    """Words preferred when suggesting spelling corrections."""
    words = english_words()
    return frozenset({v for v in ACTION_VERBS_ANY if v in words} | COMMON_RESUME_WORDS | {k.lower() for k in EXTRA_CASING})

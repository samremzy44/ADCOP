# ADCOP Application Overview

## Purpose

ADCOP (Adaptive Cognitive Diagnostic and Optimisation Platform) is a prototype
for gathering mathematics learning evidence and turning it into prompts for
follow-up teaching. Its web application focuses on learners in Grades 4–9. It
offers an assessment workflow, learner reports, educator views and
administrator account and question-bank controls.

The central idea is formative support: help learners and educators notice
which mathematics skills may need another explanation or practice opportunity.
ADCOP is not a grading, placement or psychological-diagnosis system. Its
questions, curriculum relationships and scoring rules are drafts and have not
been established as valid measures of learning.

## How the web application works

### 1. Accounts, schools and consent

The web application has three roles:

- **Learners** can complete an assessment after the required consent has been
  recorded. Learner registration includes a grade, school and province, and
  asks for confirmation that the person creating the account is authorised to
  do so.
- **Educators** register with an official EMIS school code and province. Their accounts remain
  inactive until an administrator approves them. The school dashboard and
  protocol summaries filter learners by matching `school_id` and
  accepted latest consent. Individual report routes apply role and school
  checks; consent checks vary by route and should be reviewed before deployment.
- **Administrators** can approve educators, assign school details, review
  accounts and manage the question bank.

The application includes consent withdrawal and learner-account deletion.
These controls are useful safeguards, but their presence alone does not
establish compliance with privacy law or make a deployment suitable for
children's data.

### 2. Learner assessment

The main learner-facing assessment is the **protocol diagnostic** at
`/protocol-assessment`. A learner's registered grade selects a draft,
generated question set for Grades 4–9. The blueprint groups four-step
question ladders into mathematics sub-skills and curriculum strands. A sitting
also includes warm-up questions, optional checks or challenges where specified,
an optional written method for each item, and a short learner reflection.

The learner submits the sitting once complete. The prototype applies a
provisional stop rule after two consecutive errors within a ladder. Each
sub-skill receives a descriptive result based on the number of correct ladder
answers: “Secure evidence,” “Mixed evidence - check again,” or “Needs
investigation.” These are workflow labels, not validated thresholds. Educators
can add a provisional error code, such as conceptual, procedural, fact-recall,
reading/language, or not-attempted, to support discussion of an incorrect or
unfinished item.

Learners may complete another sitting after finishing one. Each sitting is
stored independently with its own identifier, start time, completion time,
answers and results; an unfinished sitting is resumed rather than duplicated.
The application does not overwrite an earlier completed sitting when a learner
retakes the diagnostic.

### 3. Reports and follow-up

Learners can see their completed protocol report. It presents sub-skill
evidence, the learner's reflection, optional written methods and suggested
follow-up activities. A completed report can generate a downloadable PDF
worksheet with five fresh practice questions for up to three priority
sub-skills, or a short general review if no sub-skills are flagged. Educators
and administrators can download a separate answer-key version; learners
receive the worksheet without answers. Educators can also view school-level
protocol summaries, filter summaries by grade, inspect eligible learner
reports and record error codes. Learners can access their dated report history;
the protocol summary provides linked educators and administrators with a
dated list of completed reports and links to each independent report. Educator
views are limited to matching school and province and consented learners. The
administrator dashboard links to the overall report history and provides
account and question-bank management.

The dashboards also include server-rendered charts: administrators can see
accounts by role and the most-answered concepts; educators can see learners
and recorded responses by grade. The charts are designed to work without
JavaScript or an external chart service.

### 4. Data and technical components

The web application is primarily implemented in `simulate.py` using FastAPI,
server-rendered HTML and SQLite. Its in-file curriculum contains 18 draft
mathematics concepts and prerequisite relationships. Assessment sittings,
accounts, consent records, questions, answer attempts and reports are stored
in SQLite.

There are also two related but separate prototypes:

- `adcop/engine.py`, `adcop/graph.json`, `adcop/items.json` and `adcop/bot.py`
  implement a particle-based Bayesian inference experiment and a short,
  consent-based chat flow. `chat.py` is a terminal client; `server.py` is a
  provider-adaptation webhook stub. The webhook does not itself connect to a
  WhatsApp provider.
- The web application's older attempt-based concept report uses Bayesian
  estimates and the `attempts` and `mastery` tables. This is separate from the
  active protocol sitting and its stored results.

**Important reporting limitation:** protocol sittings are stored separately
from the older answer-attempt records. The dashboard's “responses by grade”
and “most-answered concepts” charts, and some older concept reports, use the
attempt-based data; they do not currently count protocol-sitting responses.
They should not be treated as complete measures of participation in the
protocol diagnostic.

## How ADCOP could support South African education

Subject to curriculum review, validation and a responsible pilot, ADCOP could
support school mathematics teaching in several practical ways:

1. **Earlier formative signals:** A short, structured assessment may help a
   teacher identify sub-skills that merit a closer look before a learner moves
   on to more complex material.
2. **More focused teaching conversations:** Item responses, method
   explanations and teacher error codes can give learners and educators
   concrete evidence to discuss, rather than relying only on a single overall
   score.
3. **Targeted practice and re-checking:** The reports suggest small practice
   activities and later checks. Teachers can adapt these to classroom work,
   textbooks and available learning materials.
4. **Shared planning:** With complete and appropriately aggregated data,
   grade- and school-level summaries could help educators identify common
   learning needs and plan group support or professional learning.
5. **A basis for local co-design:** The prototype can be used to explore how
   digital formative assessment might fit South African classrooms, including
   teacher workflows, language needs and differences in access to devices and
   connectivity.

These are potential uses, not demonstrated impacts. The application cannot
replace a teacher's professional judgement, classroom observation, learner
work, or the wider support a learner may need. Digital tools will only be
useful where the design and deployment fit local school conditions.

## Limitations and safeguards

- The question bank, generated items, grade coverage, prerequisite graph,
  probability parameters, stop rule and report categories require review by
  South African mathematics curriculum and assessment specialists.
- PDF worksheets reuse the draft protocol question generator. They are practice
  materials for discussion and review, not validated tests or guaranteed
  remediation.
- A correct multiple-choice answer is limited evidence of understanding.
  Language, accessibility, teaching opportunity, familiarity with the format
  and other factors may affect responses.
- The current protocol is not shown to be CAPS-aligned or psychometrically
  validated. Results must not be used by themselves for marks, promotion,
  streaming, placement, funding decisions or labels about a learner.
- The existing dashboards do not yet combine protocol sitting results with
  legacy attempt-based reporting. Any school-level decisions need a complete,
  clearly defined data source.
- Before use with real learners, schools and project owners should review
  consent and guardian processes, data minimisation, access controls, retention
  and deletion, hosting, incident response, and applicable South African
  privacy and child-protection obligations. This document is not legal advice.
- A production deployment also needs secure configuration, HTTPS, backups,
  monitoring, accessibility and language review, support arrangements and
  testing on the devices and connectivity available to participating schools.

## A responsible path to school use

1. **Co-design and review:** Work with mathematics educators, curriculum
   specialists, learners and relevant school communities to review the
   blueprint, question wording, languages, accessibility and consent process.
2. **Validate the measures:** Pilot items in varied school contexts. Check
   alignment, fairness, consistency and whether the results are useful to
   teachers. Revise or remove items that do not perform appropriately.
3. **Complete reporting:** Clearly separate and label protocol sittings,
   ordinary item attempts and any model-derived estimates before using
   aggregate charts for planning.
4. **Run a limited, supported pilot:** Train educators, provide a non-digital
   alternative, gather learner and teacher feedback, and avoid consequential
   decisions based on prototype results.
5. **Evaluate outcomes and equity:** Examine whether the tool improves
   teaching decisions and learning support, who benefits, and whether access,
   language or other barriers create unequal results. Expand only if evidence
   and safeguards support doing so.

## Running the prototype

From the `adcop_prototype` directory, install the listed dependencies and start
the web application:

```text
python -m pip install -r requirements.txt
python -m uvicorn simulate:app --reload
```

This command is intended for local development, not as a production hosting
configuration. Review the project README and configure secrets, HTTPS, database
storage and deployment controls before any use beyond local testing.

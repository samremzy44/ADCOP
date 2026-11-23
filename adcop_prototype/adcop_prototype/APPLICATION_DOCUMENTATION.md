# ADCOP Application Document

## 1. Purpose

ADCOP, the Adaptive Cognitive Diagnostic and Optimisation Platform, is an educational
learning-support prototype for mathematics learners in Grades 4 to 9 in South
Africa. It provides:

- A grade-specific protocol diagnostic.
- Learner progress reports.
- Draft concept-mastery estimates from the separate adaptive question-bank pathway.
- Educator and administrator dashboards.
- Optional practice worksheets.
- Separate lightweight chat and webhook prototypes.

ADCOP is not a grading, placement, promotion or psychological-diagnostic system.
Its questions, curriculum links, probability parameters and report categories are
drafts. They have not been reviewed and validated sufficiently for consequential
classroom or institutional decisions.

## 2. Intended users

### Learners

Learners can:

- Create an account and record consent.
- Complete a Grade 4 to 9 mathematics diagnostic.
- Resume an unfinished diagnostic sitting.
- View dated completed reports.
- View draft concept estimates from the adaptive question-bank pathway.
- Complete and record remedial exercises.
- Withdraw consent and request deletion of their learner account and associated records.

### Educators

Educators can:

- Register for an account.
- Wait for administrator approval.
- View learners registered at a matching school and province.
- Open consented learner reports.
- Review protocol sub-skill results.
- Record provisional C, P, F or R error codes.
- View a school-level protocol summary.
- Download an individually generated worksheet and answer key for each accessible learner report.

Educator access is not automatic. The account must be active and must match a
learner's normalized school name and province.

### Administrators

Administrators can:

- Approve educator accounts.
- Assign or update learner and educator school details.
- Review accounts and question-bank information.
- Add grade-, strand- and topic-tagged questions to the current bank.
- Download answer keys.
- View application-level aggregate charts.

## 3. Application architecture

### Web application

The main web application is [simulate.py](./simulate.py). It uses:

- FastAPI for routes and form handling.
- Server-rendered HTML for the interface.
- SQLite for persistent application data.
- ReportLab for downloadable PDF worksheets.
- Standard-library Scrypt support for password hashing.
- HMAC-signed, cookie-based sessions.

The application is primarily implemented as a single Python module. It does not
currently depend on a separate frontend framework or external chart library.

### Separate lightweight prototype

The `adcop/` package is a separate particle-Bayesian and chat experiment:

- [adcop/engine.py](./adcop/engine.py) implements graph and particle logic.
- [adcop/bot.py](./adcop/bot.py) implements consent, state replay and chat decisions.
- [adcop/graph.json](./adcop/graph.json) contains draft graph data.
- [adcop/items.json](./adcop/items.json) contains placeholder items.
- [chat.py](./chat.py) is a terminal chat client.
- [server.py](./server.py) is a webhook adaptation stub.

The `adcop/` prototype is not the same assessment workflow as the protocol
diagnostic in `simulate.py`.

## 4. Curriculum and assessment content

### Knowledge graph

`simulate.py` groups the current adaptive bank into 30 grade-and-strand
concepts for Grades 4–9. Each concept includes its grade, strand, description
and provisional prerequisite concept IDs. The current relationships are
exposed through `/api/knowledge-graph`; the former 18 concepts are returned as
archived concepts for historical compatibility.

The current groupings and graph edges are draft hypotheses, not a validated
cognitive or curriculum model.

### CAPS-aligned adaptive question bank

`QUESTION_SEED` generates 400 original questions across the five CAPS
mathematics strands. The grade totals are:

| Grade | Items |
|---|---:|
| 4 | 68 |
| 5 | 67 |
| 6 | 67 |
| 7 | 67 |
| 8 | 66 |
| 9 | 65 |

The grade allocations approximate the strand weightings in the CAPS Grades
4–6 and Grades 7–9 guides. Every generated item has a prompt, four unique
options, correct answer, explanation, grade, strand, topic and draft difficulty.
The adaptive selector does not present a learner with questions above their
registered grade.

Administrators can add tagged questions through `/admin/questions`. Existing
legacy question rows are marked inactive rather than deleted, so attempts that
reference them remain intact. Seeded current questions have stable keys and
are inserted idempotently at database startup. Question-bank records and the
legacy attempt-based adaptive pathway are separate from the protocol diagnostic.

CAPS scope alignment is not expert validation or empirical calibration. Items,
distractors and difficulty require review by a mathematics curriculum
specialist before use with learners. The bank does not constitute a validated
assessment.

### Protocol diagnostic

The active Grade 4 to 9 diagnostic is implemented by the protocol functions in
`simulate.py`. Its blueprint specifies the grade, suggested duration, maximum item
count, named sub-skills and challenge or supplementary items.

A generated sitting may contain:

- Warm-up items that are not scored.
- Core ladder items grouped by sub-skill.
- Optional supplementary or challenge items.
- Multiple-choice answers.
- Optional learner-written method explanations.
- A final reflection for each curriculum strand.

The protocol is generated when a learner starts a sitting. The learner can then
reload the page without creating a duplicate unfinished sitting.

### Official school masterlist

ADCOP includes the South African Department of Basic Education National EMIS
Quarter 2 2025 school masterlist in `emis_schools.csv`. The list is used to create
the `schools` table, with:

- `emis_code`: official National EMIS identifier.
- `name`: official institution name.
- `province`: South African province name.

The masterlist source is:
<https://www.education.gov.za/Programmes/EMIS/EMISDownloads.aspx>

## 5. Accounts and authentication

### Registration

Registration starts with a role choice and uses a role-specific form. Educators
can search the official school masterlist by name or EMIS code, confirm the
school and province, and request access. Learner forms collect a grade and
guardian/adult-authorisation confirmation; these fields are not shown on the
educator form.

School selection uses the official EMIS code and province. The application
resolves the user to a `schools` record and stores `school_id`, rather than
using a free-text school name as the authorization key. Educator registration
confirms the selected school, checks password confirmation, retains safe form
values after validation errors, and explains that access remains unavailable
until an administrator approves the request. The confirmation page explains
how to check approval status.

Passwords must contain at least 12 characters. Passwords are hashed with Scrypt
and a random 16-byte salt.

Educator accounts are created inactive and remain unavailable until an
administrator approves them. This prototype does not send email verification
or approval messages; the login page reports when an account is still pending.

### Sessions

Successful login creates an HMAC-signed session cookie. The session encodes the
user ID and expiry time. The server verifies:

- The session signature.
- The expiry timestamp.
- The current user ID.
- Whether the account is active.

The session secret should be configured through `ADCOP_SECRET` outside source
code for any persistent or production-like deployment.

### CSRF protection

State-changing form routes require a CSRF token. The token is held in an
HTTP-only cookie and submitted as a hidden form field. Requests use
constant-time signature-style comparison for verification.

### Security headers

The application middleware adds:

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy`
- A restrictive `Content-Security-Policy`

SQLite foreign-key enforcement is enabled on application database connections.

## 6. Consent and privacy

Learners must accept the prototype consent notice before protocol or legacy
assessment access. Consent records are stored separately from user accounts.

The latest consent record is authoritative. A learner who withdraws consent:

- Receives an explicit withdrawal record.
- Has their user account deleted.
- Has associated records removed through database cascades or application logic.
- Loses the session cookie.

Educator access to learner information also requires:

- An active educator account.
- A matching school name and province.
- Current learner consent.

Consent text and school/guardian workflows do not by themselves establish
compliance with applicable child protection or privacy requirements. They must
be reviewed for the jurisdiction and setting in which ADCOP is deployed.

## 7. Protocol assessment workflow

### Starting

1. The learner logs in.
2. The learner accepts consent.
3. The learner opens `/protocol-assessment`.
4. A sitting is created for the learner's registered grade.
5. An existing unfinished sitting is resumed instead of duplicated.

### Completing

The learner answers the visible items and may enter an optional written method.
At submission, the application:

- Validates that the sitting belongs to the learner.
- Checks that the sitting is still active.
- Checks submitted choices against each item's displayed options.
- Scores each item.
- Applies the provisional consecutive-error stop rule.
- Stores the original and derived result data.
- Stores the completion time and learner reflections.

The stop rule is a workflow feature, not a diagnosis:

- Two consecutive incorrect or unavailable ladder responses trigger provisional
  stopping within that ladder.
- Remaining ladder items are marked “not attempted”.
- A block needs teacher review unless enough ladder evidence is recorded.

### Reporting

Completed sittings receive independent report IDs and report URLs. Retakes do not
overwrite earlier reports.

The report includes:

- Start and completion timestamps.
- Elapsed and suggested duration.
- Sub-skill ladder results.
- Correct item counts.
- Incorrect or not-attempted items.
- Learner method explanations.
- Learner strand reflections.
- A provisional follow-up action.
- Optional teacher error codes.

## 8. Sub-skill result categories

For each ladder block, the application calculates the number of correct ladder
items.

The draft categories are:

| Correct ladder items | Category |
|---|---|
| 3 or 4 | Secure evidence |
| 2 | Mixed evidence - check again |
| 0 or 1 | Needs investigation |

These thresholds are heuristic workflow categories. They are not validated
mastery categories and do not prove that a learner has or does not have a skill.

Teachers are expected to compare the report with classroom work, explanations,
other assessment evidence and their professional judgment.

## 9. Legacy adaptive assessment

The legacy assessment at `/assessment` and its concept report use:

- `mastery` rows for one probability per learner and concept.
- `attempts` rows for every answered legacy question.
- A draft Bayesian posterior update.
- A prerequisite propagation heuristic.
- A question-selection algorithm based on uncertainty.
- Approximate uncertainty bands based on evidence count.

An answer updates the concept probability using:

- A prior probability.
- A fixed slip probability.
- A fixed guess probability.
- A bounded updated probability.

The algorithm then discounts downstream estimates when prerequisite estimates
are weak.

This mechanism is experimental:

- Probabilities are uncalibrated.
- Parameters are not empirically validated.
- The uncertainty bands are not formal confidence intervals.
- The prerequisite graph is not a validated causal model.
- The adaptive question-selection method does not demonstrate measurement validity.

Legacy results must not be interpreted as formal mastery or grade-level placement.

## 10. Reports and follow-up

### Learner report

Learners can view:

- Completed protocol report history.
- Draft concept estimates.
- Evidence counts.
- Approximate uncertainty ranges.
- A responsive learning-plan structure.
- Remedial exercise status.

### Educator learner report

Educators and administrators can review a learner's concept evidence and remedial
plan. Educators must have matching school scope and valid consent.

### Educator protocol summary

The school protocol summary shows:

- Eligible learners.
- Latest completed sitting per learner.
- Sub-skill categories.
- Shared gap counts.
- Complete dated sitting history.

The summary can be filtered by learner grade.

### Teacher error coding

For incorrect protocol items, educators and administrators can record:

- C: Conceptual gap.
- P: Procedural error.
- F: Fact recall error.
- R: Possible reading/language barrier.

The R code is a prompt to investigate language and reading effects. It is not a
diagnosis or a statement about learner ability.

For not-attempted items, the only supported code is:

- N: Not attempted or stopped by rule.

## 11. Practice worksheets

Educators can generate a separate PDF practice worksheet from each consented
learner's completed protocol report. The worksheet is available from the
individual report and the educator's report-history table, and includes the
learner's name. Learner accounts do not have a worksheet download link or
permission to access the worksheet endpoint. Educator access requires a
matching school and current learner consent; administrators can also download
worksheets.

The worksheet generator:

- Identifies sub-skills with fewer than three correct ladder responses.
- Prioritizes up to three sub-skills.
- Generates five fresh questions around a weak or broken rung.
- Uses a short general review if no sub-skill is flagged.

Educators and administrators can request a separate answer-key version. The
learner-facing report does not include a worksheet download.

Worksheet questions reuse the draft protocol generator. They have not been
curriculum reviewed or formally calibrated and are practice materials for
discussion, not validated assignments or examinations.

## 12. Dashboards

### Learner dashboard

The learner dashboard shows:

- Protocol assessment and report links.
- Legacy questions answered.
- Legacy correct-answer percentage.
- Number of concepts with evidence.
- The concept-overview table.
- Consent-withdrawal controls.

### Educator dashboard

The educator dashboard shows:

- Learners in the matching school scope.
- Legacy response totals.
- Learners and responses by grade.
- Protocol overview access.

### Administrator dashboard

The administrator dashboard shows:

- Accounts by role.
- Account and school details.
- Educator approval controls.
- The question-bank link.
- Most-answered legacy concepts.

The dashboards use server-rendered SVG charts, without an external chart service
or required chart JavaScript.

## 13. Database structure

The SQLite database is managed through `init_db()`. Major tables include:

- `schools`: official EMIS code, institution name and province.
- `users`: account details, role, grade and school scope.
- `consent`: dated consent records and guardian confirmation.
- `questions`: legacy question-bank items.
- `attempts`: individual legacy answers.
- `mastery`: legacy learner/concept estimates.
- `audit`: application actions and limited audit details.
- `remedial_plans`: legacy remedial-plan settings.
- `remedial_exercises`: individual plan exercises.
- `protocol_sittings`: protocol sitting status, answers and results.

The application uses parameterized SQL for application queries. The default
database location is `adcop.sqlite3` beside `simulate.py`, unless `ADCOP_DB`
selects another path.

## 14. API routes

Key public or authenticated routes include:

- `/health`: application health status.
- `/api/me`: currently authenticated user identity.
- `/api/knowledge-graph`: draft concepts and prerequisite edges.
- `/api/schools`: search official EMIS school records by name or code.
- `/api/learner/report`: authenticated learner's legacy report.

The knowledge-graph endpoint is public and includes an explicit disclaimer.
The report endpoint requires learner authentication and current consent.

## 15. Configuration

The application supports environment settings including:

- `ADCOP_DB`: SQLite database path.
- `ADCOP_SECRET`: persistent session-signing secret.
- `ADCOP_HTTPS`: enables secure cookies.
- `ADCOP_HOST`: host used by direct application startup.
- `ADCOP_PORT`: port used by direct application startup.
- `ADCOP_DEMO_ACCOUNTS`: opt-in demo-account creation.
- `ADCOP_DEMO_<ROLE>_USERNAME`: demo account username.
- `ADCOP_DEMO_<ROLE>_PASSWORD`: demo account password.

Demo accounts are disabled by default. Demo passwords must not be hard-coded or
committed to source control.

## 16. Running and deployment

Development startup from the prototype directory is:

```text
python -m pip install -r requirements.txt
python -m uvicorn simulate:app --reload
```

The application is intended for local development and controlled pilots. A real
deployment requires additional work for:

- Persistent secrets.
- HTTPS.
- Database backup and restore.
- Monitoring and incident response.
- Secure hosting.
- Retention and deletion procedures.
- Login throttling.
- Role and authorization testing.
- Accessibility testing.
- Data protection and safeguarding review.
- Curriculum and assessment specialist review.

## 17. Known reporting separation

Protocol sittings and legacy attempts are stored separately.

As a result:

- Protocol responses do not appear in legacy “responses by grade” charts.
- Protocol sitting counts do not appear in legacy “most-answered concepts.”
- The legacy concept report does not consume protocol sitting results.
- The protocol report is independent of the legacy Bayesian estimate.

Users and report builders should not merge the two sources until a clearly
defined data model and display rules are approved.

## 18. Current limitations

Before real or school-wide use, the application owners should address:

- CAPS and curriculum alignment.
- Expert review of protocol item wording and distractors.
- Item difficulty and measurement properties.
- Calibration of probability parameters.
- Validation of stop rules and status thresholds.
- Fairness across language, grade and learner context.
- Accessibility on available devices.
- School, parent and learner consent procedures.
- Data minimization and retention.
- Cross-sitting reporting.
- Account recovery and administrator lifecycle controls.
- Availability of a non-digital assessment alternative.
- Professional training for educators interpreting reports.
- The risk of overinterpreting prototype estimates.

## 19. Recommended responsible use

ADCOP may support a limited, supervised pilot as a conversation and follow-up
tool. It should be used alongside:

- Classroom observation.
- Teacher questioning.
- Learner explanation.
- Written or practical work.
- Existing curriculum resources.
- Professional judgment.

It should not be used alone for grades, placement, streaming, promotion,
funding, psychological decisions or labels about learner ability.

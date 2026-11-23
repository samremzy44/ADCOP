[README.md](https://github.com/user-attachments/files/35275970/README.md)
# ADCOP prototype

    pip install -r requirements.txt
    python -m uvicorn simulate:app --reload
    python chat.py          # play a learner in the terminal
    uvicorn server:app      # webhook for a WhatsApp provider (adapt parse() in server.py)

School accounts use the South African Department of Basic Education EMIS
masterlist. `emis_schools.csv` is loaded into the `schools` table at startup,
and users store a `school_id` so matching no longer depends on a typed school
name. The source masterlist is published at
https://www.education.gov.za/Programmes/EMIS/EMISDownloads.aspx.

The web app uses a grade-specific, multiple-choice Grades 4–9 protocol
diagnostic at `/protocol-assessment`. Learners can retake it after completing a
sitting; each completed sitting is stored and reported separately with its own
completion date. An unfinished sitting can be resumed. The legacy `/assessment`
route redirects to the protocol diagnostic. Learners can view their dated
report history, while linked educators and administrators can review completed
reports from `/educator/protocol-summary`.

Registration starts with a learner or educator choice. Educators can search the
official school masterlist by name or EMIS code, confirm the school and province,
and request access with a separate educator form. Requests remain pending until
an administrator approves them; the confirmation page explains how to check
approval status. Approved educators can view learner reports and protocol
summaries only for consented learners linked to the same official school.
Learners provide a grade and guardian/adult-authorisation confirmation and must
accept the consent notice before assessment. Accounts created before official
school linking can be assigned a school by an administrator.

Educators can generate an individually tailored PDF worksheet from each
consented learner's completed protocol report, either from the learner's report
or the educator report history. Learner accounts cannot download these
worksheets. Worksheets contain five new practice questions for up to three
sub-skills flagged for follow-up; if none are flagged, they provide a short
general review. Educators and administrators can also download a separate
answer-key version.
The worksheet generator uses the draft protocol question generator, so items
still require curriculum-specialist review and are not validated assessments.

The adaptive question bank contains 400 generated practice questions across
Grades 4–9 and the five CAPS mathematics strands. Each item is tagged with its
grade, strand, topic and draft difficulty. Existing legacy questions are
archived rather than deleted, preserving their recorded attempts. These bank
items are aligned to CAPS scope as a prototype, not expert-validated or
empirically calibrated; the separate protocol diagnostic has its own generated
items and still requires specialist review.

Files: adcop/graph.json (18-node draft graph), adcop/items.json (placeholder items),
adcop/engine.py (inference), adcop/bot.py (conversation + SQLite log).

NOT yet validated: curriculum graph edges, generated question-bank and protocol
items, slip/guess and prior parameters, consent text, and remediation
worksheets. Have a CAPS mathematics specialist review bank items and protocol
blueprint coverage before learner use. Diagnostic outputs are not grades or
placement recommendations.

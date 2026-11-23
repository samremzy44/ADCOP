"""ADCOP - Adaptive Cognitive Diagnostic and Optimisation Platform
Single-file educational diagnostic web application.

Run:
    pip install fastapi uvicorn
    python simulate.py
Open http://127.0.0.1:8000

For development only, demo accounts can be opt-in through ADCOP_DEMO_ACCOUNTS,
with separate username/password environment variables for each role.

"""
from __future__ import annotations

import os, json, hmac, hashlib, secrets, sqlite3, math, time, csv, socket
from contextlib import asynccontextmanager, contextmanager
from functools import lru_cache
from io import BytesIO
from html import escape as html_escape
from datetime import datetime, timezone
from typing import Optional, Any

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
import reportlab
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer

APP_NAME = "ADCOP"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("ADCOP_DB", os.path.join(BASE_DIR, "adcop.sqlite3"))
_CONFIGURED_SECRET = os.environ.get("ADCOP_SECRET")
SECRET_KEY = (
    secrets.token_urlsafe(48)
    if not _CONFIGURED_SECRET or _CONFIGURED_SECRET == "CHANGE_THIS_SECRET_BEFORE_DEPLOYMENT"
    else _CONFIGURED_SECRET
)
COOKIE_NAME = "adcop_session"
CSRF_COOKIE_NAME = "adcop_csrf"
SESSION_SECONDS = 60 * 60 * 8
SOUTH_AFRICAN_PROVINCES = (
    "Eastern Cape",
    "Free State",
    "Gauteng",
    "KwaZulu-Natal",
    "Limpopo",
    "Mpumalanga",
    "Northern Cape",
    "North West",
    "Western Cape",
)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    del _app
    init_db()
    if not _CONFIGURED_SECRET or _CONFIGURED_SECRET == "CHANGE_THIS_SECRET_BEFORE_DEPLOYMENT":
        print("WARNING: ADCOP_SECRET is not configured; using an ephemeral process secret.")
    problems = validate_graph()
    if problems:
        for problem in problems:
            print(f"Knowledge graph warning: {problem}")
    yield

app = FastAPI(title="ADCOP", description="Adaptive Cognitive Diagnostic and Optimisation Platform", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[], allow_credentials=True, allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
app.add_middleware(GZipMiddleware, minimum_size=500)

@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    return response

# -----------------------------------------------------------------------------
# 1. CURRICULUM / KNOWLEDGE GRAPH
# -----------------------------------------------------------------------------
LEGACY_CONCEPTS = [
    {"id":"fractions_intro","name":"Understanding fractions","grade":4,"description":"Recognise fractions as equal parts of a whole.","prerequisites":[]},
    {"id":"multiplication","name":"Multiplication","grade":4,"description":"Multiply whole numbers and understand multiplication facts.","prerequisites":[]},
    {"id":"division","name":"Division","grade":4,"description":"Divide whole numbers and interpret remainders.","prerequisites":["multiplication"]},
    {"id":"equivalent_fractions","name":"Equivalent fractions","grade":5,"description":"Identify and generate equivalent fractions.","prerequisites":["fractions_intro","multiplication"]},
    {"id":"factors_multiples","name":"Factors and multiples","grade":5,"description":"Identify factors, multiples and common factors.","prerequisites":["multiplication","division"]},
    {"id":"lcm_hcf","name":"LCM and HCF","grade":5,"description":"Calculate the lowest common multiple and highest common factor.","prerequisites":["factors_multiples"]},
    {"id":"fraction_operations","name":"Operations with fractions","grade":6,"description":"Add, subtract, multiply and divide fractions.","prerequisites":["equivalent_fractions","multiplication","division"]},
    {"id":"decimals","name":"Decimals and percentages","grade":6,"description":"Work with decimal notation and percentage relationships.","prerequisites":["multiplication","division","fractions_intro"]},
    {"id":"integers","name":"Integers","grade":7,"description":"Compare and calculate with positive and negative integers.","prerequisites":["multiplication","division"]},
    {"id":"ratios","name":"Ratios and rates","grade":7,"description":"Represent and simplify ratios and solve rate problems.","prerequisites":["multiplication","division","fractions_intro"]},
    {"id":"algebra_expressions","name":"Algebraic expressions","grade":7,"description":"Represent quantities using variables and simplify expressions.","prerequisites":["multiplication","division"]},
    {"id":"exponents","name":"Exponents","grade":8,"description":"Apply exponent notation and basic exponent laws.","prerequisites":["multiplication","division"]},
    {"id":"linear_equations","name":"Linear equations","grade":8,"description":"Solve one-variable linear equations.","prerequisites":["algebra_expressions","integers"]},
    {"id":"factorisation","name":"Factorisation","grade":8,"description":"Factorise simple algebraic expressions.","prerequisites":["algebra_expressions","multiplication"]},
    {"id":"algebraic_fractions","name":"Algebraic fractions","grade":9,"description":"Simplify and operate with algebraic fractions.","prerequisites":["fraction_operations","factorisation","linear_equations"]},
    {"id":"quadratics","name":"Quadratic equations","grade":9,"description":"Solve basic quadratic equations using factorisation.","prerequisites":["factorisation","linear_equations","exponents"]},
    {"id":"functions","name":"Functions and graphs","grade":9,"description":"Interpret function notation, tables and graphs.","prerequisites":["linear_equations","algebra_expressions"]},
    {"id":"proportionality","name":"Direct and inverse proportion","grade":9,"description":"Solve direct and inverse proportionality problems.","prerequisites":["ratios","linear_equations"]},
]
LEGACY_CONCEPT_BY_ID = {c["id"]: c for c in LEGACY_CONCEPTS}

# Three starter items per concept. These are seed examples; educators should review
# wording, curriculum alignment, distractors and difficulty before learner use.
LEGACY_QUESTION_SEED = {
"fractions_intro":[("Which fraction represents one of four equal parts?",["1/2","1/3","1/4","4/1"],"1/4","A fraction names equal parts of a whole."),("In 3/5, what does the 5 represent?",["Numerator","Denominator","Whole number","Remainder"],"Denominator","The denominator tells how many equal parts make the whole."),("Which is the larger fraction?",["1/3","1/2","They are equal","Cannot tell"],"1/2","One half is larger than one third." )],
"multiplication":[("What is 7 × 6?",["36","42","48","56"],"42","Seven groups of six make 42."),("What is 9 × 4?",["32","34","36","40"],"36","9 multiplied by 4 equals 36."),("A box has 8 rows of 5 pencils. How many pencils are there?",["13","35","40","45"],"40","8 × 5 = 40." )],
"division":[("What is 48 ÷ 6?",["6","7","8","9"],"8","Division asks how many groups of six fit into 48."),("What is 63 ÷ 9?",["6","7","8","9"],"7","9 × 7 = 63."),("Share 20 sweets equally among 4 learners. How many each?",["4","5","6","8"],"5","20 divided by 4 equals 5." )],
"equivalent_fractions":[("Which fraction is equivalent to 1/2?",["2/3","2/4","3/4","1/4"],"2/4","Multiply numerator and denominator by the same number."),("Complete: 3/5 = ?/10",["3","5","6","8"],"6","5 was multiplied by 2, so 3 must also be multiplied by 2."),("Which pair is equivalent?",["1/2 and 2/4","1/3 and 1/4","2/3 and 3/5","3/4 and 2/3"],"1/2 and 2/4","Both fractions represent the same value." )],
"factors_multiples":[("Which number is a factor of 24?",["5","7","8","10"],"8","24 ÷ 8 = 3 with no remainder."),("Which is a multiple of 7?",["25","28","30","32"],"28","7 × 4 = 28."),("What is the greatest factor of 18 other than 18?",["3","6","9","12"],"9","The factors of 18 are 1, 2, 3, 6, 9 and 18." )],
"lcm_hcf":[("What is the HCF of 12 and 18?",["2","3","6","9"],"6","6 is the greatest number that divides both."),("What is the LCM of 4 and 6?",["8","10","12","24"],"12","12 is the smallest positive common multiple."),("The HCF of 8 and 20 is…",["2","4","5","8"],"4","The common factors are 1, 2 and 4." )],
"fraction_operations":[("What is 1/4 + 1/4?",["1/8","1/4","1/2","2/8"],"1/2","Add numerators when denominators are the same: 2/4 = 1/2."),("What is 2/3 × 3/4?",["1/2","5/7","6/7","6/12"],"1/2","Multiply numerators and denominators, then simplify."),("What is 1/2 ÷ 1/4?",["1/8","1/2","2","4"],"2","Dividing by one quarter asks how many quarters fit into one half." )],
"decimals":[("What is 0.5 as a percentage?",["5%","25%","50%","500%"],"50%","Multiply a decimal by 100 to convert to a percentage."),("What is 2.35 + 1.4?",["2.49","3.39","3.75","4.75"],"3.75","Align decimal places before adding."),("What is 25% of 80?",["10","15","20","25"],"20","25% is one quarter; 80 ÷ 4 = 20." )],
"integers":[("What is -3 + 7?",["-10","-4","4","10"],"4","Moving seven units right from -3 gives 4."),("What is -4 × 3?",["-12","-7","7","12"],"-12","A negative multiplied by a positive is negative."),("Which number is smallest?",["-2","0","-5","3"],"-5","Numbers further left on the number line are smaller." )],
"ratios":[("Simplify the ratio 6:9.",["1:2","2:3","3:4","6:3"],"2:3","Divide both parts by their HCF, 3."),("A mixture uses 2 cups water for every 1 cup juice. How many cups water for 3 cups juice?",["3","4","5","6"],"6","The ratio is 2:1, so multiply both parts by 3."),("If 4 notebooks cost R40, what is the cost of one?",["R5","R10","R20","R160"],"R10","R40 ÷ 4 = R10." )],
"algebra_expressions":[("Simplify 3x + 2x.",["5","5x","6x","x"],"5x","Like terms can be combined by adding coefficients."),("If a = 4, what is 2a + 3?",["9","10","11","14"],"11","Substitute 4: 2(4) + 3 = 11."),("Which expression means 5 more than n?",["5n","n - 5","n + 5","n/5"],"n + 5","More than indicates addition." )],
"exponents":[("What is 2³?",["5","6","8","9"],"8","2³ = 2 × 2 × 2 = 8."),("What is 5²?",["10","15","20","25"],"25","5² means 5 multiplied by itself."),("Simplify 3² × 3¹.",["3³","3²","3¹","9³"],"3³","When multiplying powers with the same base, add exponents." )],
"linear_equations":[("Solve x + 5 = 12.",["5","7","12","17"],"7","Subtract 5 from both sides."),("Solve 3x = 21.",["6","7","8","9"],"7","Divide both sides by 3."),("Solve 2x - 4 = 10.",["3","5","7","9"],"7","Add 4, then divide by 2." )],
"factorisation":[("Factorise 3x + 6.",["3(x + 2)","3(x + 6)","x(3 + 6)","6(x + 3)"],"3(x + 2)","Take out the common factor 3."),("Factorise x² + 5x.",["x(x + 5)","5(x + 1)","x²(1 + 5)","(x + 5)²"],"x(x + 5)","Both terms contain a factor of x."),("Factorise 4a - 8.",["4(a - 2)","2(4a - 8)","4(a - 8)","a(4 - 8)"],"4(a - 2)","The greatest common factor is 4." )],
"algebraic_fractions":[("Simplify 6x/3.",["2","2x","3x","6/x"],"2x","Divide the coefficient 6 by 3."),("Simplify x/2 + x/2.",["x/4","x/2","x","2x"],"x","The denominators are equal, so add the numerators."),("For x ≠ 0, simplify 3x/x.",["x","3","3x","1/3"],"3","Cancel the common non-zero factor x." )],
"quadratics":[("Solve x² = 25.",["x = 5 only","x = -5 only","x = ±5","x = 25"],"x = ±5","Both 5² and (-5)² equal 25."),("Factorise x² + 5x + 6.",["(x+2)(x+3)","(x+1)(x+6)","(x-2)(x-3)","(x+5)(x+1)"],"(x+2)(x+3)","2 and 3 multiply to 6 and add to 5."),("Solve x² - 9 = 0.",["x = 9","x = ±3","x = 3 only","x = 0"],"x = ±3","x² = 9, so x can be 3 or -3." )],
"functions":[("If f(x) = 2x, what is f(3)?",["2","3","5","6"],"6","Replace x with 3: 2 × 3 = 6."),("For y = x + 4, what is y when x = 2?",["2","4","6","8"],"6","Substitute x = 2."),("In y = 3x, what is the gradient?",["1","2","3","0"],"3","The coefficient of x is the gradient." )],
"proportionality":[("If 2 items cost R30, what do 4 items cost at the same rate?",["R45","R60","R75","R90"],"R60","Doubling the quantity doubles the cost."),("If 4 workers take 6 days, how many days would 8 workers take at the same rate?",["2","3","6","12"],"3","With twice as many workers, the time is halved."),("Which equation shows direct proportion?",["y = kx","y = k/x","y = x + k","y = k - x"],"y = kx","In direct proportion, the ratio y/x is constant." )]
}

CAPS_STRANDS = {
    "numbers": "Numbers, Operations and Relationships",
    "patterns": "Patterns, Functions and Algebra",
    "geometry": "Space and Shape (Geometry)",
    "measurement": "Measurement",
    "data": "Data Handling",
}

CAPS_QUESTION_COUNTS = {
    4: {"numbers":34,"patterns":7,"geometry":10,"measurement":10,"data":7},
    5: {"numbers":34,"patterns":7,"geometry":10,"measurement":10,"data":6},
    6: {"numbers":34,"patterns":7,"geometry":10,"measurement":10,"data":6},
    7: {"numbers":20,"patterns":17,"geometry":17,"measurement":7,"data":6},
    8: {"numbers":17,"patterns":20,"geometry":16,"measurement":7,"data":6},
    9: {"numbers":10,"patterns":23,"geometry":19,"measurement":7,"data":6},
}
CAPS_QUESTION_BANK_SIZE = 400
if sum(
    count for grade_counts in CAPS_QUESTION_COUNTS.values() for count in grade_counts.values()
) != CAPS_QUESTION_BANK_SIZE:
    raise ValueError("CAPS question allocations must total exactly 400 items")
CAPS_QUESTION_SEED_VERSION = "caps-2023-v2"

CONCEPTS = [
    {
        "id":f"caps_g{grade}_{key}",
        "name":f"Grade {grade}: {strand}",
        "description":f"CAPS Grade {grade} practice for {strand}.",
        "grade":grade,
        "strand":strand,
        "strand_key":key,
        "prerequisites":[f"caps_g{grade - 1}_{key}"] if grade > 4 else [],
    }
    for grade, grade_counts in CAPS_QUESTION_COUNTS.items()
    for key in grade_counts
    for strand in (CAPS_STRANDS[key],)
]
CONCEPT_BY_ID = {
    **LEGACY_CONCEPT_BY_ID,
    **{concept["id"]:concept for concept in CONCEPTS},
}
CURRENT_CONCEPT_IDS = {concept["id"] for concept in CONCEPTS}


def _caps_number(value: int) -> str:
    return f"{value:,}"


def _caps_fraction(numerator: int, denominator: int) -> str:
    divisor = math.gcd(numerator, denominator)
    return f"{numerator // divisor}/{denominator // divisor}"


def _caps_item(
    topic: str,
    prompt: str,
    answer: Any,
    distractors: list[Any],
    explanation: str,
    difficulty: int,
    salt: int,
) -> dict[str, Any]:
    correct = str(answer)
    options = []
    for option in [correct] + [str(value) for value in distractors]:
        if option not in options:
            options.append(option)
    if len(options) != 4:
        raise ValueError(f"CAPS question needs four distinct options: {prompt}")
    offset = salt % len(options)
    options = options[offset:] + options[:offset]
    return {
        "topic":topic,
        "prompt":prompt,
        "options":options,
        "answer":correct,
        "explanation":explanation,
        "difficulty":difficulty,
    }


def _caps_number_question(grade: int, index: int, difficulty: int, salt: int) -> dict[str, Any]:
    variant = index // 8
    mode = index % 8
    if grade == 4:
        if mode == 0:
            number = 2_431 + variant * 137
            place = (1_000,100,10,1)[variant % 4]
            digit = number // place % 10
            answer = digit * place
            wrong = [digit, answer + place, max(0, answer - place)]
            if place == 1:
                wrong = [answer + 1, answer + 2, max(0, answer - 1)]
            if answer == 0:
                wrong = [place, place * 2, place * 3]
            return _caps_item("Place value",f"In {_caps_number(number)}, what is the value of the digit {digit}?",_caps_number(answer),[_caps_number(x) for x in wrong],f"The digit {digit} is in the {place:,} place, so its value is {answer:,}.",difficulty,salt)
        if mode == 1:
            number = 1_324 + variant * 113
            unit = (10,100,1_000)[variant % 3]
            rounded = (number + unit // 2) // unit * unit
            return _caps_item("Rounding whole numbers",f"Round {_caps_number(number)} to the nearest {_caps_number(unit)}.",_caps_number(rounded),[_caps_number(rounded + unit),_caps_number(rounded - unit),_caps_number(number)],f"Rounding {_caps_number(number)} to the nearest {_caps_number(unit)} gives {_caps_number(rounded)}.",difficulty,salt)
        if mode == 2:
            a,b = 2_307 + variant * 113, 825 + variant * 29
            answer = a + b
            return _caps_item("Addition and subtraction",f"Calculate {_caps_number(a)} + {_caps_number(b)}.",_caps_number(answer),[_caps_number(answer + 10),_caps_number(answer - 10),_caps_number(answer + 100)],f"Add the place values: {a:,} + {b:,} = {answer:,}.",difficulty,salt)
        if mode == 3:
            a,b = 24 + variant * 3, 13 + variant
            answer = a * b
            return _caps_item("Multiplication",f"Calculate {a} × {b}.",_caps_number(answer),[_caps_number(answer + a),_caps_number(answer - b),_caps_number(a + b)],f"{a} × {b} = {answer}.",difficulty,salt)
        if mode == 4:
            divisor,quotient = 3 + variant % 6, 126 + variant * 9
            dividend = divisor * quotient
            return _caps_item("Division",f"Calculate {_caps_number(dividend)} ÷ {divisor}.",_caps_number(quotient),[_caps_number(quotient + divisor),_caps_number(quotient - 1),_caps_number(dividend - divisor)],f"{dividend:,} ÷ {divisor} = {quotient}.",difficulty,salt)
        if mode == 5:
            denominator = 6 + variant % 5
            a = 1 + variant % 2
            b = 1 + (variant + 1) % (denominator - a)
            answer = _caps_fraction(a + b,denominator)
            return _caps_item("Common fractions",f"Calculate {a}/{denominator} + {b}/{denominator}.",answer,[_caps_fraction(a,denominator),_caps_fraction(b,denominator),_caps_fraction(a + b + 1,denominator)],f"Add the numerators: {a}/{denominator} + {b}/{denominator} = {a + b}/{denominator}, which simplifies to {answer}.",difficulty,salt)
        if mode == 6:
            factor = 4 + variant
            multiple = factor * (5 + variant)
            answer = _caps_number(multiple)
            return _caps_item("Multiples and factors",f"Which number is a multiple of {factor}?",answer,[_caps_number(multiple - 1),_caps_number(multiple + 1),_caps_number(multiple + 3)],f"{factor} × {5 + variant} = {multiple}, so {multiple} is a multiple of {factor}.",difficulty,salt)
        groups,each = 6 + variant, 8 + variant * 2
        answer = groups * each
        return _caps_item("Multiplication in context",f"A school packs {each} exercise books in each of {groups} boxes. How many books are packed?",_caps_number(answer),[_caps_number(answer + each),_caps_number(answer - groups),_caps_number(groups + each)],f"Multiply the number of boxes by the books in each box: {groups} × {each} = {answer}.",difficulty,salt)

    if grade == 5:
        if mode == 0:
            number = 352_417 + variant * 12_031
            unit = (10,100,1_000,10_000)[variant % 4]
            rounded = (number + unit // 2) // unit * unit
            return _caps_item("Place value and rounding",f"Round {_caps_number(number)} to the nearest {_caps_number(unit)}.",_caps_number(rounded),[_caps_number(rounded + unit),_caps_number(rounded - unit),_caps_number(number)],f"The nearest {_caps_number(unit)} to {_caps_number(number)} is {_caps_number(rounded)}.",difficulty,salt)
        if mode == 1:
            a,b = 42_713 + variant * 1_107, 18_206 + variant * 213
            answer = a - b
            return _caps_item("Addition and subtraction",f"Calculate {_caps_number(a)} − {_caps_number(b)}.",_caps_number(answer),[_caps_number(answer + 10),_caps_number(answer - 10),_caps_number(a + b)],f"Subtract by place value: {a:,} − {b:,} = {answer:,}.",difficulty,salt)
        if mode == 2:
            a,b = 123 + variant * 17, 12 + variant % 6
            answer = a * b
            return _caps_item("Multiplication",f"Calculate {a} × {b}.",_caps_number(answer),[_caps_number(answer + a),_caps_number(answer - b),_caps_number(a + b)],f"{a} × {b} = {answer}.",difficulty,salt)
        if mode == 3:
            divisor,quotient = 12 + variant % 8, 15 + variant * 3
            dividend = divisor * quotient
            return _caps_item("Division",f"Calculate {_caps_number(dividend)} ÷ {divisor}.",_caps_number(quotient),[_caps_number(quotient + 1),_caps_number(quotient - 1),_caps_number(dividend - divisor)],f"{dividend:,} ÷ {divisor} = {quotient}.",difficulty,salt)
        if mode == 4:
            a,b = 18 + variant * 2, 30 + variant * 3
            answer = math.gcd(a,b)
            return _caps_item("Factors and common factors",f"What is the highest common factor of {a} and {b}?",answer,[a,b,answer + 1],f"The common factors of {a} and {b} include {answer}; no larger common factor divides both.",difficulty,salt)
        if mode == 5:
            a,b,denominator = 1 + variant % 2, 1 + variant % 3, 4 + variant % 3
            answer = _caps_fraction(a * 2 + b,denominator * 2)
            return _caps_item("Equivalent fractions",f"Calculate {a}/{denominator} + {b}/{denominator * 2}.",answer,[_caps_fraction(a,denominator),_caps_fraction(b,denominator * 2),_caps_fraction(a * 2 + b + 1,denominator * 2)],f"Write {a}/{denominator} as {a * 2}/{denominator * 2}, then add to get {a * 2 + b}/{denominator * 2} = {answer}.",difficulty,salt)
        if mode == 6:
            a = (125 + variant * 17) / 100
            b = (75 + variant * 11) / 100
            answer = f"{a + b:.2f}"
            return _caps_item("Decimal fractions",f"Calculate {a:.2f} + {b:.2f}.",answer,[f"{a + b + .1:.2f}",f"{a + b - .1:.2f}",f"{a + b + 1:.2f}"],f"Align the decimal places: {a:.2f} + {b:.2f} = {answer}.",difficulty,salt)
        ratio_a,ratio_b = 2 + variant, 3 + variant
        total = (ratio_a + ratio_b) * (4 + variant)
        first_share = ratio_a * (4 + variant)
        return _caps_item("Ratio and sharing",f"A total of {total} counters is shared in the ratio {ratio_a}:{ratio_b}. How many counters are in the first share?",first_share,[first_share + ratio_a,first_share - ratio_a,total - first_share],f"There are {ratio_a + ratio_b} equal parts. Each is {4 + variant}; the first share is {ratio_a} × {4 + variant} = {first_share}.",difficulty,salt)

    if grade == 6:
        if mode == 0:
            number = 324_561_789 + variant * 10_021_003
            place = (100_000_000,10_000_000,1_000_000,100_000,10_000)[variant % 5]
            digit = number // place % 10
            answer = digit * place
            return _caps_item("Place value",f"In {_caps_number(number)}, what is the value of the digit {digit}?",_caps_number(answer),[_caps_number(digit),_caps_number(answer + place),_caps_number(max(0,answer - place))],f"The digit {digit} is in the {place:,} place, so its value is {answer:,}.",difficulty,salt)
        if mode == 1:
            a,b = 1_234 + variant * 137, 126 + variant * 11
            answer = a * b
            return _caps_item("Whole-number operations",f"Calculate {_caps_number(a)} × {b}.",_caps_number(answer),[_caps_number(answer + a),_caps_number(answer - b),_caps_number(a + b)],f"{a:,} × {b} = {answer:,}.",difficulty,salt)
        if mode == 2:
            prime = (2,3,5,7,11)[variant % 5]
            number = prime * (13 + variant * 2)
            return _caps_item("Prime factors",f"Which is a prime factor of {number}?",prime,[number,prime + 1,2 * prime],f"{number} = {prime} × {13 + variant * 2}, and {prime} is prime.",difficulty,salt)
        if mode == 3:
            denominator = 8 + variant * 2
            a,b = 1 + variant % 3, 1 + (variant + 1) % 4
            answer = _caps_fraction(a + b,denominator)
            return _caps_item("Fraction operations",f"Calculate {a}/{denominator} + {b}/{denominator}.",answer,[_caps_fraction(a + b + offset,denominator) for offset in (1,2,3)],f"Add the numerators: {a}/{denominator} + {b}/{denominator} = {a + b}/{denominator} = {answer}.",difficulty,salt)
        if mode == 4:
            percent = (10,20,25,50)[variant % 4]
            whole = (240,360,480,640,800)[variant % 5]
            answer = whole * percent // 100
            return _caps_item("Percentages",f"What is {percent}% of {whole}?",answer,[answer + percent,answer - percent,whole + percent],f"{percent}% of {whole} is {whole} × {percent}/100 = {answer}.",difficulty,salt)
        if mode == 5:
            value = 2.35 + variant * .42
            multiplier = 10 if variant % 2 == 0 else 100
            answer = f"{value * multiplier:.2f}".rstrip("0").rstrip(".")
            return _caps_item("Decimal fractions",f"Calculate {value:.2f} × {multiplier}.",answer,[f"{value * multiplier + 1:.2f}".rstrip("0").rstrip("."),f"{value * multiplier - 1:.2f}".rstrip("0").rstrip("."),f"{value / multiplier:.3f}".rstrip("0").rstrip(".")],f"Multiplying {value:.2f} by {multiplier} moves the decimal point {1 if multiplier == 10 else 2} place(s) right, giving {answer}.",difficulty,salt)
        if mode == 6:
            rate,quantity = 18 + variant * 3, 4 + variant
            total = rate * quantity
            return _caps_item("Rates",f"A cyclist travels {total} km in {quantity} hours at a constant rate. What is the rate in kilometres per hour?",f"{rate} km/h",[f"{rate + 2} km/h",f"{quantity} km/h",f"{total} km/h"],f"Rate = distance ÷ time = {total} ÷ {quantity} = {rate} km/h.",difficulty,salt)
        divisor,quotient = 125 + variant * 25, 32 + variant * 7
        dividend = divisor * quotient
        return _caps_item("Division in context",f"{_caps_number(dividend)} seedlings are placed equally in {divisor} trays. How many seedlings go in each tray?",quotient,[quotient + 1,quotient - 1,divisor],f"{dividend:,} ÷ {divisor} = {quotient} seedlings per tray.",difficulty,salt)

    if grade == 7:
        if mode == 0:
            a,b = 18 + variant * 3, 11 + variant * 2
            answer = b - a
            return _caps_item("Integers",f"Calculate (−{a}) + {b}.",answer,[a - b,a + b,-a - b],f"Starting at −{a} and moving {b} units right gives {answer}.",difficulty,salt)
        if mode == 1:
            a,b = 5 + variant, 3 + variant % 4
            answer = -a * b
            return _caps_item("Integer multiplication",f"Calculate (−{a}) × {b}.",answer,[a * b,-a - b,a - b],f"A negative multiplied by a positive is negative: (−{a}) × {b} = {answer}.",difficulty,salt)
        if mode == 2:
            a,b,denominator = 1 + variant % 3, 1 + variant % 4, 5 + variant
            answer = _caps_fraction(a + b,denominator)
            return _caps_item("Common fractions",f"Calculate {a}/{denominator} + {b}/{denominator}.",answer,[_caps_fraction(a + b + offset,denominator) for offset in (1,2,3)],f"Add the numerators and simplify: {a + b}/{denominator} = {answer}.",difficulty,salt)
        if mode == 3:
            percent,whole = (10,15,20,25,30)[variant % 5], 200 + variant * 40
            answer = whole * percent // 100
            return _caps_item("Percentages",f"A jacket costs R{whole}. It is discounted by {percent}%. What is the discount amount?",f"R{answer}",[f"R{answer + 10}",f"R{whole - answer}",f"R{percent}"],f"The discount is {percent}/100 × R{whole} = R{answer}.",difficulty,salt)
        if mode == 4:
            a,b = 3 + variant, 4 + variant
            total = (a + b) * (5 + variant)
            first = a * (5 + variant)
            return _caps_item("Ratio and sharing",f"{total} seedlings are shared in the ratio {a}:{b}. How many seedlings are in the first share?",first,[first + a,first - a,total - first],f"The total number of parts is {a + b}; each part is {5 + variant}. The first share is {a} × {5 + variant} = {first}.",difficulty,salt)
        if mode == 5:
            base,exponent = 2 + variant % 4, 2 + variant % 3
            answer = base ** exponent
            return _caps_item("Exponents",f"Calculate {base}^{exponent}.",answer,[answer + 1,answer - 1,answer * 2],f"{base}^{exponent} means {base} multiplied by itself {exponent} times, which is {answer}.",difficulty,salt)
        if mode == 6:
            principal,rate,years = 500 + variant * 100, 4 + variant, 2
            interest = principal * rate * years // 100
            return _caps_item("Simple interest",f"R{principal} is invested at {rate}% simple interest per year for {years} years. How much interest is earned?",f"R{interest}",[f"R{principal * rate // 100}",f"R{principal + interest}",f"R{interest + rate}"],f"Simple interest = principal × rate × time = R{principal} × {rate}/100 × {years} = R{interest}.",difficulty,salt)
        a,b = 3_241 + variant * 127, 1_806 + variant * 89
        answer = a + b
        return _caps_item("Whole-number operations",f"Calculate {_caps_number(a)} + {_caps_number(b)}.",_caps_number(answer),[_caps_number(answer + 100),_caps_number(answer - 100),_caps_number(a - b)],f"{a:,} + {b:,} = {answer:,}.",difficulty,salt)

    if grade == 8:
        if mode == 0:
            a,b,c = 12 + variant * 2, 5 + variant, 9 + variant * 2
            answer = -a + b * c
            return _caps_item("Integer operations",f"Calculate (−{a}) + {b} × {c}.",answer,[-a + b + c,-(a + b * c),a + b * c],f"Multiply first: {b} × {c} = {b*c}; then add −{a} to get {answer}.",difficulty,salt)
        if mode == 1:
            base,m,n = 2 + variant, 2 + variant % 3, 1 + variant % 2
            answer = f"{base}^{m+n}"
            return _caps_item("Laws of exponents",f"Simplify {base}^{m} × {base}^{n}.",answer,[f"{base}^{m+n+1}",f"{base}^{m+n-1}",f"{base*2}^{m+n}"],f"When multiplying powers with the same base, add exponents: {base}^{m} × {base}^{n} = {base}^{m+n}.",difficulty,salt)
        if mode == 2:
            a,b,c,d = 1 + variant, 2 + variant, 3 + variant, 4 + variant
            answer = _caps_fraction(a * c,b * d)
            return _caps_item("Fraction multiplication",f"Calculate {a}/{b} × {c}/{d}.",answer,[_caps_fraction(a,b),_caps_fraction(c,d),_caps_fraction(a*c + b*d,b*d)],f"Multiply numerators and denominators, then simplify: {a*c}/{b*d} = {answer}.",difficulty,salt)
        if mode == 3:
            ratio_a,ratio_b = 2 + variant, 3 + variant
            batches = ratio_b * (3 + variant)
            answer = ratio_a * (3 + variant)
            return _caps_item("Ratio and proportion",f"A recipe uses {ratio_a} cups of flour for {ratio_b} batches. How many cups are needed for {batches} batches?",_caps_number(answer),[_caps_number(answer + ratio_a),_caps_number(batches),_caps_number(answer - ratio_b)],f"Scale the recipe by {3 + variant}: {ratio_a} × {3 + variant} = {answer} cups.",difficulty,salt)
        if mode == 4:
            principal,rate,years = 800 + variant * 100, 5 + variant, 2
            interest = principal * rate * years // 100
            return _caps_item("Financial mathematics",f"R{principal} earns {rate}% simple interest per year for {years} years. What is the total amount?",f"R{principal + interest}",[f"R{principal + rate * years}",f"R{interest}",f"R{principal + interest + rate}"],f"Interest = R{principal} × {rate}/100 × {years} = R{interest}; total = R{principal + interest}.",difficulty,salt)
        if mode == 5:
            coefficient,exponent = 3 + variant, 3 + variant % 3
            answer = coefficient * 10 ** exponent
            return _caps_item("Scientific notation",f"Write {coefficient} × 10^{exponent} as an ordinary number.",_caps_number(answer),[_caps_number(coefficient * exponent),_caps_number(coefficient * 10 ** (exponent - 1)),_caps_number(coefficient * 10 ** (exponent + 1))],f"Multiplying by 10^{exponent} moves the decimal point {exponent} places right: {answer:,}.",difficulty,salt)
        if mode == 6:
            base = 4 + variant
            answer = base * base
            return _caps_item("Squares and square roots",f"What is the square root of {answer}?",base,[base + 1,answer // 2,base * base],f"{base} × {base} = {answer}, so the square root of {answer} is {base}.",difficulty,salt)
        percent,whole = (20,25,30,40)[variant % 4], 320 + variant * 80
        answer = whole * percent // 100
        return _caps_item("Percentages",f"What is {percent}% of {whole}?",answer,[answer + percent,answer - percent,whole + percent],f"{percent}% of {whole} is {whole} × {percent}/100 = {answer}.",difficulty,salt)

    if mode == 0:
        numerator,denominator = 3 + variant, 5 + variant
        answer = _caps_fraction(numerator,denominator)
        return _caps_item("Rational numbers",f"Simplify the fraction {numerator * 2}/{denominator * 2}.",answer,[_caps_fraction(numerator + 1,denominator),_caps_fraction(numerator,denominator * 2),_caps_fraction(numerator * 2,denominator)],f"Divide the numerator and denominator by 2: {numerator * 2}/{denominator * 2} = {answer}.",difficulty,salt)
    if mode == 1:
        exponent = 2 + variant
        base = 10
        answer = f"10^{exponent}"
        return _caps_item("Exponents and scientific notation",f"Simplify 10^{exponent + 1} ÷ 10.",answer,[f"10^{exponent + 1}",f"10^{exponent - 1}",f"10^{exponent * 10}"],f"Divide powers with the same base by subtracting exponents: 10^{exponent + 1} ÷ 10^1 = 10^{exponent}.",difficulty,salt)
    if mode == 2:
        rate,quantity = 24 + variant * 6, 3 + variant
        total = rate * quantity
        return _caps_item("Direct proportion",f"{quantity} identical notebooks cost R{total}. At the same rate, how much does one notebook cost?",f"R{rate}",[f"R{rate + 2}",f"R{total}",f"R{total + rate}"],f"Unit price = R{total} ÷ {quantity} = R{rate}.",difficulty,salt)
    if mode == 3:
        principal,rate,years = 1_000 + variant * 500, 10, 2
        amount = principal * (1 + rate / 100) ** years
        rounded = round(amount)
        return _caps_item("Compound interest",f"R{principal} is invested at {rate}% compound interest per year for {years} years. What is the amount after 2 years?",f"R{rounded}",[f"R{principal + principal * rate * years // 100}",f"R{rounded + 100}",f"R{principal + principal * rate // 100}"],f"Apply the rate each year: R{principal} × 1.10 × 1.10 = R{rounded}.",difficulty,salt)
    if mode == 4:
        number = 16 + variant * 4
        return _caps_item("Real number system",f"Which statement about √{number * number + 1} is correct?", "It is irrational",["It is a natural number","It is an integer","It is a terminating decimal"],f"{number * number + 1} is not a perfect square, so its square root is irrational.",difficulty,salt)
    commission_variant = variant * 3 + mode - 5
    percent,amount = 8 + commission_variant, 1_500 + commission_variant * 250
    commission = amount * percent // 100
    return _caps_item("Percentages and financial contexts",f"A sales commission is {percent}% of sales of R{amount}. What is the commission?",f"R{commission}",[f"R{commission + 10}",f"R{amount - commission}",f"R{percent}"],f"Commission = {percent}/100 × R{amount} = R{commission}.",difficulty,salt)


def _caps_patterns_question(grade: int, index: int, difficulty: int, salt: int) -> dict[str, Any]:
    variant = index // 5
    mode = index % 5
    if grade <= 6:
        grade_offset = grade - 4
        repeat = mode // 3
        if mode % 3 == 0:
            start,step = 7 + (variant + grade_offset) * 3 + repeat * 5, 4 + variant + repeat
            terms = [start + step * n for n in range(4)]
            answer = terms[-1] + step
            return _caps_item("Numeric patterns",f"Continue the pattern: {', '.join(map(str,terms))}, __.",answer,[answer + 1,answer - 1,answer + step],f"The pattern increases by {step} each time, so the next term is {answer}.",difficulty,salt)
        if mode % 3 == 1:
            multiplier,addend,input_value = 2 + (variant + grade_offset + repeat) % 3, 3 + (variant + grade_offset) * 2 + repeat, 5 + variant + repeat
            answer = multiplier * input_value + addend
            return _caps_item("Input and output values",f"A flow rule multiplies the input by {multiplier} and then adds {addend}. What is the output for input {input_value}?",answer,[answer + multiplier,answer - addend,multiplier + addend],f"Apply the rule: {input_value} × {multiplier} + {addend} = {answer}.",difficulty,salt)
        a,b = 23 + variant * 7 + grade_offset * 5, 68 + variant * 9 + grade_offset * 10
        answer = b - a
        return _caps_item("Number sentences",f"Complete the number sentence: {a} + □ = {b}.",answer,[answer + 1,answer - 1,a + b],f"The missing number is {b} − {a} = {answer}.",difficulty,salt)
    if grade == 7:
        if mode == 0:
            start,step = 5 + variant * 2, 3 + variant
            terms = [start + step * n for n in range(4)]
            answer = terms[-1] + step
            return _caps_item("Numeric patterns",f"What is the next term? {', '.join(map(str,terms))}, __.",answer,[answer + step,answer - step,answer + 1],f"The constant difference is {step}; the next term is {answer}.",difficulty,salt)
        if mode == 1:
            coefficient,constant = 3 + variant, 5 + variant * 2
            return _caps_item("Algebraic language",f"In the expression {coefficient}x + {constant}, which symbol is the variable?","x",[str(coefficient),str(constant),"+"],"The variable is the symbol whose value may change; here it is x.",difficulty,salt)
        if mode == 2:
            value,x = 2 + variant, 4 + variant
            answer = 3 * x + value
            return _caps_item("Substitution",f"Find the value of 3n + {value} when n = {x}.",answer,[3 + x + value,3 * x - value,3 * (x + value)],f"Substitute n = {x}: 3 × {x} + {value} = {answer}.",difficulty,salt)
        if mode == 3:
            a,b = 19 + variant * 3, 52 + variant * 5
            answer = b - a
            return _caps_item("Number sentences",f"Solve □ + {a} = {b}.",answer,[answer + 1,answer - 1,a + b],f"Subtract {a} from both sides: □ = {b} − {a} = {answer}.",difficulty,salt)
        multiplier,addend,input_value = 2 + variant, 4 + variant * 3, 6 + variant
        answer = multiplier * input_value + addend
        return _caps_item("Functions and relationships",f"The rule is y = {multiplier}x + {addend}. Find y when x = {input_value}.",answer,[answer + multiplier,answer - addend,multiplier * (input_value + addend)],f"Substitute x = {input_value}: y = {multiplier}({input_value}) + {addend} = {answer}.",difficulty,salt)
    if grade == 8:
        if mode == 0:
            start,step = 4 + variant * 3, 5 + variant
            terms = [start + step * n for n in range(4)]
            answer = terms[-1] + step
            return _caps_item("Numeric and geometric patterns",f"What is the next term? {', '.join(map(str,terms))}, __.",answer,[answer + 1,answer - step,answer + step],f"The sequence increases by {step} each time; the next term is {answer}.",difficulty,salt)
        if mode == 1:
            a,b,c = 3 + variant, 5 + variant, 2 + variant
            answer = f"{a + b}x + {c}"
            return _caps_item("Simplifying expressions",f"Simplify {a}x + {b}x + {c}.",answer,[f"{a + b + c}x",f"{a * b}x + {c}",f"{a + b}x − {c}"],f"Combine like terms: {a}x + {b}x = {a + b}x; the constant {c} remains.",difficulty,salt)
        if mode == 2:
            coefficient,constant,x = 2 + variant, 7 + variant * 2, 5 + variant
            total = coefficient * x + constant
            return _caps_item("Linear equations",f"Solve {coefficient}x + {constant} = {total}.",x,[x + 1,x - 1,total // coefficient],f"Subtract {constant}, then divide by {coefficient}: x = ({total} − {constant})/{coefficient} = {x}.",difficulty,salt)
        if mode == 3:
            a,b = 4 + variant, 7 + variant * 2
            answer = a * b
            return _caps_item("Expanding expressions",f"Expand {a}(x + {b}).",f"{a}x + {answer}",[f"{a}x + {b}",f"{a + b}x",f"{a}x − {answer}"],f"Distribute {a}: {a}(x + {b}) = {a}x + {a*b}.",difficulty,salt)
        multiplier,addend,input_value = 3 + variant, 2 + variant, 4 + variant
        answer = multiplier * input_value + addend
        return _caps_item("Functions and relationships",f"For y = {multiplier}x + {addend}, what is y when x = {input_value}?",answer,[answer + multiplier,answer - addend,multiplier + input_value + addend],f"Substitute x = {input_value}: y = {multiplier}({input_value}) + {addend} = {answer}.",difficulty,salt)
    if mode == 0:
        start,step = 6 + variant * 2, 5 + variant
        terms = [start + step * n for n in range(4)]
        answer = terms[-1] + step
        return _caps_item("Numeric patterns",f"Find the next term: {', '.join(map(str,terms))}, __.",answer,[answer + step,answer - 1,answer + 1],f"The constant difference is {step}, so the next term is {answer}.",difficulty,salt)
    if mode == 1:
        a,b,c = 4 + variant, 3 + variant, 7 + variant
        answer = f"{a + b}x + {c}"
        return _caps_item("Algebraic expressions",f"Simplify {a}x + {b}x + {c}.",answer,[f"{a + b + c}x",f"{a * b}x + {c}",f"{a + b}x − {c}"],f"Add the coefficients of the like terms: {a}x + {b}x = {a + b}x.",difficulty,salt)
    if mode == 2:
        coefficient,constant,x = 3 + variant, 8 + variant * 2, 4 + variant
        total = coefficient * x + constant
        return _caps_item("Linear equations",f"Solve {coefficient}x + {constant} = {total}.",x,[x + 1,x - 1,total - constant],f"Subtract {constant} and divide by {coefficient}; x = {x}.",difficulty,salt)
    if mode == 3:
        multiplier,addend,input_value = 2 + variant, 5 + variant * 2, 3 + variant
        output = multiplier * input_value + addend
        return _caps_item("Functions and graphs",f"The linear rule is y = {multiplier}x + {addend}. What is the output when x = {input_value}?",output,[output + multiplier,output - addend,multiplier * (input_value + addend)],f"Substitute x = {input_value}: y = {multiplier} × {input_value} + {addend} = {output}.",difficulty,salt)
    if mode == 4:
        p,q = 2 + variant, 4 + variant
        b,c = p + q,p * q
        answer = f"(x + {p})(x + {q})"
        return _caps_item("Factorisation",f"Factorise x² + {b}x + {c}.",answer,[f"(x + 1)(x + {c})",f"(x − {p})(x − {q})",f"(x + {b})(x + {q})"],f"The numbers {p} and {q} add to {b} and multiply to {c}; therefore x² + {b}x + {c} = {answer}.",difficulty,salt)
    p,q = 2 + variant, 3 + variant
    b,c = p + q,p * q
    answer = f"x + {q}"
    return _caps_item("Algebraic fractions",f"Simplify (x² + {b}x + {c})/(x + {p}), where x ≠ −{p}.",answer,[f"x + {p}",f"x + {b}",f"x² + {q}"],f"Factor the numerator: (x + {p})(x + {q}); cancel the non-zero factor (x + {p}) to get {answer}.",difficulty,salt)


def _caps_geometry_question(grade: int, index: int, difficulty: int, salt: int) -> dict[str, Any]:
    variant = index // 6
    mode = index % 6
    if grade <= 6:
        if mode == 0:
            sides = (3,4,5,6,7,8)[((grade - 4) * 2 + index // 6) % 6]
            names = {3:"triangle",4:"quadrilateral",5:"pentagon",6:"hexagon",7:"heptagon",8:"octagon"}
            answer = names[sides]
            wrong = [name for name in ("triangle","square","pentagon","hexagon","heptagon","octagon") if name != answer][:3]
            return _caps_item("Properties of 2-D shapes",f"What is the name of a polygon with {sides} sides?",answer,wrong,f"A polygon with {sides} sides is a {answer}.",difficulty,salt)
        if mode == 1:
            shape,attribute,answer = (
                ("cube","faces","6"),
                ("cube","vertices","8"),
                ("rectangular prism","edges","12"),
                ("sphere","flat faces","0"),
                ("cylinder","curved surfaces","1"),
                ("triangular prism","faces","5"),
            )[((grade - 4) * 2 + index // 6) % 6]
            wrong = ["4","8","12","1","0"]
            wrong = [item for item in wrong if item != answer][:3]
            return _caps_item("Properties of 3-D objects",f"How many {attribute} does a {shape} have?",answer,wrong,f"A {shape} has {answer} {attribute}.",difficulty,salt)
        if mode == 2:
            shape,count = (
                ("square",4),
                ("rectangle",2),
                ("equilateral triangle",3),
                ("regular hexagon",6),
                ("circle",None),
                ("regular pentagon",5),
            )[((grade - 4) * 2 + index // 6) % 6]
            if count is None:
                return _caps_item("Symmetry",f"Which shape has infinitely many lines of symmetry?","Circle",["Square","Rectangle","Equilateral triangle"],"Every diameter of a circle is a line of symmetry, so it has infinitely many.",difficulty,salt)
            return _caps_item("Symmetry",f"How many lines of symmetry does a {shape} have?",count,[count + 1,max(0,count - 1),count + 2],f"A {shape} has {count} line(s) of symmetry.",difficulty,salt)
        if mode == 3:
            if grade == 4:
                shape,count = (("square",4),("rectangle",4),("triangle",3),("pentagon",5),("hexagon",6))[variant % 5]
                return _caps_item("Properties of 2-D shapes",f"How many sides does a {shape} have?",count,[count + 1,count - 1,count + 2],f"A {shape} has {count} sides.",difficulty,salt)
            scenario = (grade - 5) * 2 + variant
            distance = 3 + scenario
            direction = ("right","left","up")[scenario % 3]
            return _caps_item("Transformations",f"A shape moves {distance} squares {direction} without turning or flipping. Which transformation occurred?","Translation",["Reflection","Rotation","Enlargement"],"A translation slides every point the same distance in the same direction.",difficulty,salt)
        if mode == 4:
            if grade == 4:
                shape,faces = (("cube",6),("rectangular prism",6),("cylinder",2),("sphere",0))[variant % 4]
                wrong = [1,2,3] if faces == 0 else [faces + 2,faces - 1,faces + 3]
                return _caps_item("3-D objects",f"How many flat faces does a {shape} have?",faces,wrong,f"A {shape} has {faces} flat face(s).",difficulty,salt)
            angle = 90 + (variant + grade - 5) * 15
            kind = "acute" if angle < 90 else ("right" if angle == 90 else "obtuse")
            wrong = [item for item in ("acute","right","obtuse","straight") if item != kind][:3]
            return _caps_item("Angles",f"An angle of {angle}° is which type of angle?",kind,wrong,f"{angle}° is a {kind} angle.",difficulty,salt)
        combination = (grade - 4) * 2 + index // 6
        directions = ("north","east","south","west")
        direction_index = combination % len(directions)
        turn = 90 if combination < 4 else 180
        answer = directions[(direction_index + turn // 90) % len(directions)]
        wrong = [item for item in directions if item != answer]
        return _caps_item("Position and direction",f"A learner faces {directions[direction_index]} and turns {turn}° clockwise. Which direction is the learner facing?",answer,wrong,f"A {turn}° clockwise turn moves {turn // 90} compass quarter-turn(s).",difficulty,salt)

    if grade == 7:
        if mode == 0:
            equal_sides = (2,3,0)[variant % 3]
            answer = {0:"Scalene triangle",2:"Isosceles triangle",3:"Equilateral triangle"}[equal_sides]
            wrong = [item for item in ("Scalene triangle","Isosceles triangle","Equilateral triangle","Right-angled triangle") if item != answer][:3]
            side_description = "no" if equal_sides == 0 else str(equal_sides)
            return _caps_item("Classifying triangles",f"A triangle has {side_description} equal sides. Which classification applies?",answer,wrong,f"A triangle with {side_description} equal sides is {answer.lower()}.",difficulty,salt)
        if mode == 1:
            property_name,answer = (("both pairs of opposite sides parallel and only opposite sides equal","parallelogram"),("four equal sides and four right angles","square"),("exactly one pair of parallel sides","trapezium"))[variant % 3]
            return _caps_item("Classifying quadrilaterals",f"Which quadrilateral has {property_name}?",answer,["Triangle","Circle","Pentagon"],f"A {answer} has {property_name}.",difficulty,salt)
        if mode == 2:
            term,description = (("parallel lines","lines that remain the same distance apart"),("perpendicular lines","lines that meet at a right angle"),("line segment","part of a line with two endpoints"))[variant % 3]
            return _caps_item("Geometry of straight lines",f"Which term matches this description: {description}?",term,["Ray","Circle","Angle"],f"{description.capitalize()} describes {term}.",difficulty,salt)
        if mode == 3:
            angle = 35 + variant * 7
            kind = "acute"
            return _caps_item("Measuring angles",f"An angle measures {angle}°. How is it classified?",kind,["Right","Obtuse","Straight"],f"{angle}° is less than 90°, so the angle is acute.",difficulty,salt)
        if mode == 4:
            original = 2 + variant
            scale = 2 + variant % 3
            answer = original * scale
            return _caps_item("Enlargement and reduction",f"A side of a shape is {original} cm. It is enlarged by scale factor {scale}. What is the corresponding side length?",f"{answer} cm",[f"{answer + 1} cm",f"{answer - 1} cm",f"{answer * 2} cm"],f"Multiply the original length by the scale factor: {original} × {scale} = {answer} cm.",difficulty,salt)
        east,north = 4 + variant,2 + variant
        return _caps_item("Transformations",f"A point moves {east} squares east and {north} squares north. Which transformation describes the move?","Translation",["Reflection","Rotation","Enlargement"],"A translation moves each point by the same distance and direction.",difficulty,salt)

    if grade == 8:
        if mode == 0:
            angle = 38 + variant * 9
            return _caps_item("Angle relationships",f"Two straight lines intersect. One angle is {angle}°. What is the vertically opposite angle?",f"{angle}°",[f"{180-angle}°",f"{90-angle}°",f"{angle+90}°"],"Vertically opposite angles are equal.",difficulty,salt)
        if mode == 1:
            angle = 112 + variant * 7
            answer = 180 - angle
            return _caps_item("Parallel lines and transversals",f"Co-interior angles between parallel lines sum to 180°. One is {angle}°. Find the other.",f"{answer}°",[f"{angle}°",f"{180+angle}°",f"{90-angle}°"],f"Co-interior angles sum to 180°: 180° − {angle}° = {answer}°.",difficulty,salt)
        if mode == 2:
            shape,attribute,answer = (("triangular prism","edges",9),("triangular prism","vertices",6),("cube","edges",12),("cube","faces",6))[variant % 4]
            return _caps_item("Classifying 3-D objects",f"How many {attribute} does a {shape} have?",answer,[answer + 1,answer - 1,answer + 2],f"A {shape} has {answer} {attribute}.",difficulty,salt)
        if mode == 3:
            x,y = 2 + variant, -3 - variant
            return _caps_item("Coordinate transformations",f"Reflect the point ({x}, {y}) in the x-axis. What are the image coordinates?",f"({x}, {abs(y)})",[f"({-x}, {y})",f"({-x}, {-y})",f"({x}, {y})"],"Reflection in the x-axis keeps x the same and changes the sign of y.",difficulty,salt)
        if mode == 4:
            angle_a,angle_b = 42 + variant * 3, 58 + variant * 2
            answer = 180 - angle_a - angle_b
            return _caps_item("Triangle angle sum",f"Two angles of a triangle are {angle_a}° and {angle_b}°. What is the third angle?",f"{answer}°",[f"{angle_a + angle_b}°",f"{180-angle_a}°",f"{180-angle_b}°"],f"Triangle angles sum to 180°: 180° − {angle_a}° − {angle_b}° = {answer}°.",difficulty,salt)
        scale,side = 2 + variant, 3 + variant
        return _caps_item("Similar shapes",f"Corresponding sides of similar triangles are in the ratio 1:{scale}. A side on the smaller triangle is {side} cm. What is the corresponding larger side?",f"{side * scale} cm",[f"{side + scale} cm",f"{side * (scale + 1)} cm",f"{side} cm"],f"Multiply the smaller side by the scale factor: {side} × {scale} = {side * scale} cm.",difficulty,salt)

    if mode == 0:
        angle = 48 + variant * 6
        return _caps_item("Angle relationships",f"Two parallel lines are cut by a transversal. A corresponding angle is {angle}°. Find the matching corresponding angle.",f"{angle}°",[f"{180-angle}°",f"{90-angle}°",f"{angle+90}°"],"Corresponding angles on parallel lines are equal.",difficulty,salt)
    if mode == 1:
        criterion,condition,explanation = (
            ("SSS","all three pairs of corresponding sides are equal","SSS means all three corresponding side pairs are equal."),
            ("SAS","two corresponding sides and the included angle are equal","SAS means two side pairs and their included angle are equal."),
            ("ASA","two corresponding angles and the included side are equal","ASA means two angle pairs and their included side are equal."),
        )[variant % 3]
        wrong = [key for key in ("SSS","SAS","ASA") if key != criterion] + ["AAA"]
        return _caps_item("Congruent triangles",f"Which congruence criterion applies when {condition}?",criterion,wrong,explanation,difficulty,salt)
    if mode == 2:
        x,y = -4 - variant, 2 + variant
        return _caps_item("Coordinate transformations",f"Reflect ({x}, {y}) in the y-axis.",f"({-x}, {y})",[f"({x}, {-y})",f"({-x}, {-y})",f"({x}, {y})"],"Reflection in the y-axis changes the sign of x and keeps y unchanged.",difficulty,salt)
    if mode == 3:
        angle_a,angle_b = 35 + variant * 4, 67 + variant * 3
        answer = 180 - angle_a - angle_b
        return _caps_item("Triangle properties",f"A triangle has angles {angle_a}° and {angle_b}°. Find its third angle.",f"{answer}°",[f"{angle_a + angle_b}°",f"{180-angle_a}°",f"{180-angle_b}°"],f"The angles in a triangle sum to 180°; the missing angle is {answer}°.",difficulty,salt)
    if mode == 4:
        side,scale = 4 + variant, 2 + variant
        return _caps_item("Similar triangles",f"A triangle is enlarged by scale factor {scale}. A corresponding side was {side} cm. What is its new length?",f"{side*scale} cm",[f"{side+scale} cm",f"{side*(scale+1)} cm",f"{side} cm"],f"Multiply the original side by {scale}: {side} × {scale} = {side*scale} cm.",difficulty,salt)
    solid,attribute,answer = (("square pyramid","vertices",5),("rectangular prism","faces",6),("square pyramid","edges",8))[variant % 3]
    return _caps_item("3-D objects",f"How many {attribute} does a {solid} have?",answer,[answer + 1,answer + 2,answer + 3],f"A {solid} has {answer} {attribute}.",difficulty,salt)


def _caps_measurement_question(grade: int, index: int, difficulty: int, salt: int) -> dict[str, Any]:
    variant = index // 6
    mode = index % 6
    if grade <= 6:
        variant += (grade - 4) * 3
        if mode == 0:
            amount = 125 + variant * 25
            return _caps_item("Length",f"Convert {amount} cm to millimetres.",f"{amount * 10} mm",[f"{amount} mm",f"{amount * 100} mm",f"{amount // 10} mm"],f"1 cm = 10 mm, so {amount} cm = {amount * 10} mm.",difficulty,salt)
        if mode == 1:
            amount = 2 + variant
            return _caps_item("Mass and capacity",f"Convert {amount} kg to grams.",f"{amount * 1_000} g",[f"{amount * 100} g",f"{amount * 10} g",f"{amount * 10_000} g"],f"1 kg = 1,000 g, so {amount} kg = {amount * 1_000} g.",difficulty,salt)
        if mode == 2:
            start_hour,start_minute,duration = 8 + variant, 15 + variant * 5, 65 + variant * 10
            total = start_hour * 60 + start_minute + duration
            answer = f"{(total // 60) % 24:02d}:{total % 60:02d}"
            return _caps_item("Time",f"A lesson starts at {start_hour:02d}:{start_minute:02d} and lasts {duration} minutes. When does it finish?",answer,[f"{(total // 60) % 24:02d}:{(total % 60 + 10) % 60:02d}",f"{(start_hour + 1) % 24:02d}:{start_minute:02d}",f"{(total // 60 + 1) % 24:02d}:{total % 60:02d}"],f"Add {duration} minutes to {start_hour:02d}:{start_minute:02d}; the finish time is {answer}.",difficulty,salt)
        if mode == 3:
            length,width = 8 + variant, 5 + variant
            perimeter = 2 * (length + width)
            return _caps_item("Perimeter",f"A rectangle is {length} cm long and {width} cm wide. What is its perimeter?",f"{perimeter} cm",[f"{length * width} cm",f"{length + width} cm",f"{perimeter + 2} cm"],f"Perimeter = 2 × ({length} + {width}) = {perimeter} cm.",difficulty,salt)
        if mode == 4:
            squares = 12 + variant * 3
            return _caps_item("Area by square units",f"A shape covers {squares} unit squares on a grid. What is its area?",f"{squares} square units",[f"{squares + 2} square units",f"{squares - 2} square units",f"{2 * squares} square units"],f"Count the unit squares covered: the area is {squares} square units.",difficulty,salt)
        amount = 3 + variant
        return _caps_item("Capacity",f"Convert {amount} litres to millilitres.",f"{amount * 1_000} ml",[f"{amount * 100} ml",f"{amount * 10} ml",f"{amount * 10_000} ml"],f"1 litre = 1,000 ml, so {amount} litres = {amount * 1_000} ml.",difficulty,salt)

    if grade == 7:
        if mode == 0:
            length,width = 12 + variant, 7 + variant
            area = length * width
            return _caps_item("Area and perimeter",f"A rectangle measures {length} cm by {width} cm. What is its area?",f"{area} cm²",[f"{2*(length+width)} cm²",f"{length+width} cm²",f"{area+length} cm²"],f"Area = length × width = {length} × {width} = {area} cm².",difficulty,salt)
        if mode == 1:
            side = 4 + variant
            volume = side ** 3
            return _caps_item("Surface area and volume",f"What is the volume of a cube with side length {side} cm?",f"{volume} cm³",[f"{6*side*side} cm³",f"{side*side} cm³",f"{3*side} cm³"],f"Volume = side³ = {side}³ = {volume} cm³.",difficulty,salt)
        if mode == 2:
            amount = 12 + variant * 3
            return _caps_item("SI unit conversions",f"Convert {amount} cm to metres.",f"{amount / 100:.2f} m",[f"{amount / 10:.2f} m",f"{amount * 100:.2f} m",f"{amount / 1_000:.3f} m"],f"100 cm = 1 m, so {amount} cm = {amount / 100:.2f} m.",difficulty,salt)
        if mode == 3:
            length,width,height = 5 + variant, 3 + variant, 2 + variant
            volume = length * width * height
            return _caps_item("Volume of rectangular prisms",f"Find the volume of a rectangular prism measuring {length} cm × {width} cm × {height} cm.",f"{volume} cm³",[f"{2*(length*width+length*height+width*height)} cm³",f"{length*width} cm³",f"{length+width+height} cm³"],f"Volume = length × width × height = {length} × {width} × {height} = {volume} cm³.",difficulty,salt)
        if mode == 4:
            length,width = 10 + variant, 6 + variant
            perimeter = 2 * (length + width)
            return _caps_item("Perimeter",f"Calculate the perimeter of a rectangle with sides {length} cm and {width} cm.",f"{perimeter} cm",[f"{length*width} cm",f"{perimeter+2} cm",f"{length+width} cm"],f"Perimeter = 2({length} + {width}) = {perimeter} cm.",difficulty,salt)
        area = 30 + variant * 5
        return _caps_item("Area",f"A rectangle has area {area} cm² and width {5 + variant} cm. What is its length?",f"{area // (5 + variant)} cm",[f"{area + (5 + variant)} cm",f"{5 + variant} cm",f"{area} cm"],f"Length = area ÷ width = {area} ÷ {5 + variant} = {area // (5 + variant)} cm.",difficulty,salt)

    if grade == 8:
        if mode == 0:
            a,b = (3,4) if variant % 2 == 0 else (5,12)
            hypotenuse = math.isqrt(a*a+b*b)
            return _caps_item("Theorem of Pythagoras",f"A right-angled triangle has shorter sides {a} cm and {b} cm. Find the hypotenuse.",f"{hypotenuse} cm",[f"{a+b} cm",f"{hypotenuse+1} cm",f"{abs(b-a)} cm"],f"By Pythagoras, c² = {a}² + {b}² = {a*a+b*b}; therefore c = {hypotenuse} cm.",difficulty,salt)
        if mode == 1:
            radius = 3 + variant
            circumference = 2 * 3.14 * radius
            return _caps_item("Circles",f"Use π = 3.14. What is the circumference of a circle with radius {radius} cm?",f"{circumference:.2f} cm",[f"{3.14*radius*radius:.2f} cm",f"{3.14*radius:.2f} cm",f"{circumference+3.14:.2f} cm"],f"Circumference = 2πr = 2 × 3.14 × {radius} = {circumference:.2f} cm.",difficulty,salt)
        if mode == 2:
            a,b = 9 + variant * 2, 4 + variant
            area = a * b
            return _caps_item("Area of polygons",f"A rectangle measures {a} cm by {b} cm. Find its area.",f"{area} cm²",[f"{2*(a+b)} cm²",f"{a+b} cm²",f"{area+a} cm²"],f"Area = length × width = {a} × {b} = {area} cm².",difficulty,salt)
        if mode == 3:
            length,width,height = 6 + variant, 4 + variant, 3 + variant
            volume = length * width * height
            return _caps_item("Volume of prisms",f"Find the volume of a rectangular prism measuring {length} cm × {width} cm × {height} cm.",f"{volume} cm³",[f"{2*(length*width+length*height+width*height)} cm³",f"{length*width} cm³",f"{length+width+height} cm³"],f"Volume = {length} × {width} × {height} = {volume} cm³.",difficulty,salt)
        if mode == 4:
            amount = 2 + variant
            return _caps_item("Area unit conversions",f"Convert {amount} m² to cm².",f"{amount * 10_000} cm²",[f"{amount * 100} cm²",f"{amount * 1_000} cm²",f"{amount * 100_000} cm²"],f"1 m² = 10,000 cm², so {amount} m² = {amount * 10_000} cm².",difficulty,salt)
        amount = 1 + variant
        return _caps_item("Capacity and volume",f"Convert {amount} litres to millilitres.",f"{amount * 1_000} ml",[f"{amount * 100} ml",f"{amount * 10} ml",f"{amount * 10_000} ml"],f"1 litre = 1,000 ml, so {amount} litres = {amount * 1_000} ml.",difficulty,salt)

    if mode == 0:
        a,b = (6,8) if variant % 2 == 0 else (8,15)
        hypotenuse = math.isqrt(a*a+b*b)
        return _caps_item("Theorem of Pythagoras",f"A right-angled triangle has shorter sides {a} cm and {b} cm. Find the hypotenuse.",f"{hypotenuse} cm",[f"{a+b} cm",f"{hypotenuse+1} cm",f"{abs(b-a)} cm"],f"c² = {a}² + {b}² = {a*a+b*b}, so c = {hypotenuse} cm.",difficulty,salt)
    if mode == 1:
        radius = 4 + variant
        area = 3.14 * radius * radius
        return _caps_item("Area of circles",f"Use π = 3.14. Find the area of a circle with radius {radius} cm.",f"{area:.2f} cm²",[f"{2*3.14*radius:.2f} cm²",f"{area+3.14:.2f} cm²",f"{3.14*radius:.2f} cm²"],f"Area = πr² = 3.14 × {radius}² = {area:.2f} cm².",difficulty,salt)
    if mode == 2:
        radius = 2 + variant
        height = 5 + variant
        volume = 3.14 * radius * radius * height
        return _caps_item("Volume of cylinders",f"Use π = 3.14. Find the volume of a cylinder with radius {radius} cm and height {height} cm.",f"{volume:.2f} cm³",[f"{volume+3.14:.2f} cm³",f"{volume-3.14:.2f} cm³",f"{volume*2:.2f} cm³"],f"Volume = πr²h = 3.14 × {radius}² × {height} = {volume:.2f} cm³.",difficulty,salt)
    if mode == 3:
        length,width = 13 + variant, 8 + variant
        area = length * width
        return _caps_item("Area and perimeter",f"Find the area of a rectangle {length} cm long and {width} cm wide.",f"{area} cm²",[f"{2*(length+width)} cm²",f"{length+width} cm²",f"{area+width} cm²"],f"Area = {length} × {width} = {area} cm².",difficulty,salt)
    if mode == 4:
        amount = 3 + variant
        return _caps_item("SI unit conversions",f"Convert {amount} km² to m².",f"{amount * 1_000_000} m²",[f"{amount * 1_000} m²",f"{amount * 10_000} m²",f"{amount * 100_000} m²"],f"1 km² = 1,000,000 m², so {amount} km² = {amount * 1_000_000} m².",difficulty,salt)
    side,height = 4 + variant, 6 + variant
    volume = side * side * height
    return _caps_item("Volume and scaling",f"A rectangular prism has a square base of side {side} cm and height {height} cm. What is its volume?",f"{volume} cm³",[f"{2*side*side+4*side*height} cm³",f"{side*height} cm³",f"{side+side+height} cm³"],f"Volume = base area × height = {side}² × {height} = {volume} cm³.",difficulty,salt)


def _caps_data_question(grade: int, index: int, difficulty: int, salt: int) -> dict[str, Any]:
    variant = index // 5
    mode = index % 5
    if grade <= 6:
        variant += (grade - 4) * 3
        if mode == 0:
            a,b,c,d = 4 + variant, 6 + variant * 2, 3 + variant, 5 + variant
            answer = a + b + c + d
            return _caps_item("Collecting and organizing data",f"A class recorded {a} votes for apples, {b} for bananas, {c} for pears and {d} for plums. How many votes were recorded?",answer,[answer + 2,answer - 2,b + d],f"Add the category counts: {a} + {b} + {c} + {d} = {answer}.",difficulty,salt)
        if mode == 1:
            values = [3 + variant,5 + variant * 2,4 + variant,7 + variant * 2]
            answer = max(values)
            labels = ["Monday","Tuesday","Wednesday","Thursday"]
            day = labels[values.index(answer)]
            wrong = [label for label in labels if label != day][:3]
            return _caps_item("Representing data",f"A bar graph shows books borrowed: {', '.join(f'{labels[i]} {values[i]}' for i in range(4))}. On which day were the most books borrowed?",day,wrong,f"The greatest frequency is {answer}, recorded on {day}.",difficulty,salt)
        if mode == 2:
            first,second = 5 + variant, 3 + variant
            return _caps_item("Reading pictographs",f"In a pictograph, one symbol represents one learner. If {first} symbols show learners who walk and {second} show learners who cycle, how many more walk than cycle?",first - second,[first + second,second - first,first],f"Subtract the smaller count: {first} − {second} = {first - second}.",difficulty,salt)
        if mode == 3:
            if grade == 4:
                return _caps_item("Probability experiments",f"A fair coin is tossed. Which list gives all possible outcomes?","Head and tail",["Head only","Tail only","Head, tail and side"],"A coin has two possible outcomes: head or tail.",difficulty,salt)
            outcomes = 8 + variant * 2
            red = 3 + variant
            return _caps_item("Probability experiments",f"A spinner is spun {outcomes} times and lands on red {red} times. How many spins did not land on red?",outcomes - red,[red,outcomes + red,outcomes - red + 1],f"Non-red outcomes = {outcomes} − {red} = {outcomes - red}.",difficulty,salt)
        if grade <= 5:
            counts = [2 + variant,5 + variant,3 + variant,4 + variant]
            greatest = max(counts)
            category = ("red","blue","green","yellow")[counts.index(greatest)]
            return _caps_item("Mode",f"Colours counted in a survey: red {counts[0]}, blue {counts[1]}, green {counts[2]}, yellow {counts[3]}. Which colour is the mode?",category,["red","blue","green","yellow"],f"{category.capitalize()} has the greatest frequency, {greatest}, so it is the mode.",difficulty,salt)
        counts = [3 + variant,4 + variant,5 + variant,6 + variant]
        values = sorted([1 + variant,3 + variant,3 + variant,9 + variant,10 + variant])
        median = values[len(values)//2]
        mean = sum(values) // len(values)
        return _caps_item("Median",f"Find the median of the ordered data set {', '.join(map(str,values))}.",median,[median - 1,median + 1,mean],f"The middle value in the ordered data set is {median}.",difficulty,salt)

    if grade == 7:
        if mode == 0:
            start = 3 + variant + 2 * (grade - 7)
            values = [start + 2 * i for i in range(5)]
            mean = sum(values) // len(values)
            return _caps_item("Mean",f"Find the mean of {', '.join(map(str,values))}.",mean,[mean + 1,mean - 1,values[0]],f"Mean = total ÷ number of values = {sum(values)} ÷ 5 = {mean}.",difficulty,salt)
        if mode == 1:
            low,high = 4 + variant, 19 + variant * 2
            return _caps_item("Range",f"The smallest score is {low} and the largest is {high}. What is the range?",high - low,[high + low,high - low + 1,low],f"Range = largest − smallest = {high} − {low} = {high-low}.",difficulty,salt)
        if mode == 2:
            favorable,total = 3,6
            return _caps_item("Probability",f"A fair six-sided die is rolled. What is the probability of rolling an even number?","1/2",["1/6","1/3","2/3"],"Three of the six equally likely outcomes are even, so the probability is 3/6 = 1/2.",difficulty,salt)
        if mode == 3:
            trials,successes = 20 + variant * 5, 8 + variant * 2
            return _caps_item("Relative frequency",f"A coin lands on heads {successes} times in {trials} tosses. What is the relative frequency of heads?",_caps_fraction(successes,trials),[_caps_fraction(successes + 1,trials),_caps_fraction(trials - successes,trials),_caps_fraction(successes,trials + 1)],f"Relative frequency = number of heads ÷ number of tosses = {successes}/{trials}.",difficulty,salt)
        return _caps_item("Sampling and data sources","A school wants every Grade 7 learner's opinion about lunch. Which method best represents the whole grade?","Survey learners from every Grade 7 class",["Ask only the sports team","Ask only learners in one friendship group","Ask the first five learners at the gate"],"Sampling across every class is more representative than selecting one narrow group.",difficulty,salt)

    if grade == 8:
        if mode == 0:
            start = 3 + variant + 2 * (grade - 7)
            values = [start + 2 * i for i in range(5)]
            mean = sum(values) // len(values)
            return _caps_item("Measures of central tendency",f"Find the mean of {', '.join(map(str,values))}.",mean,[mean + 2,mean - 2,values[0]],f"Add the five values and divide by 5: {sum(values)} ÷ 5 = {mean}.",difficulty,salt)
        if mode == 1:
            values = [2 + variant,5 + variant,5 + variant,9 + variant,14 + variant]
            return _caps_item("Mode",f"Find the mode of {', '.join(map(str,values))}.",f"{5 + variant}",[f"{2+variant}",f"{9+variant}",f"{14+variant}"],f"{5 + variant} occurs most often, so it is the mode.",difficulty,salt)
        if mode == 2:
            low,high = 6 + variant, 24 + variant * 2
            return _caps_item("Range and dispersion",f"Find the range of the data set with minimum {low} and maximum {high}.",high - low,[high + low,high - low + 2,high],f"Range = {high} − {low} = {high-low}.",difficulty,salt)
        if mode == 3:
            favorable,total = 3 + variant, 8 + variant * 2
            answer = _caps_fraction(favorable,total)
            return _caps_item("Probability",f"A spinner has {total} equal sections, {favorable} of them blue. What is the probability of landing on blue?",answer,[_caps_fraction(favorable + 1,total),_caps_fraction(total - favorable,total),_caps_fraction(favorable,total + 1)],f"Probability = favourable outcomes ÷ total outcomes = {favorable}/{total} = {answer}.",difficulty,salt)
        trials,successes = 24 + variant * 4, 9 + variant * 3
        return _caps_item("Relative frequency",f"An event occurs {successes} times in {trials} trials. What is its relative frequency?",_caps_fraction(successes,trials),[_caps_fraction(successes + 1,trials),_caps_fraction(trials-successes,trials),_caps_fraction(successes,trials + 1)],f"Relative frequency = {successes}/{trials}.",difficulty,salt)

    if mode == 0:
        start = 3 + variant + 2 * (grade - 7)
        values = [start + 2 * i for i in range(5)]
        mean = sum(values) // len(values)
        return _caps_item("Measures of central tendency",f"Find the mean of {', '.join(map(str,values))}.",mean,[mean + 2,mean - 2,values[0]],f"Mean = {sum(values)} ÷ 5 = {mean}.",difficulty,salt)
    if mode == 1:
        values = [2 + variant,4 + variant,6 + variant,8 + variant,20 + variant]
        median = sorted(values)[2]
        mean = sum(values) // len(values)
        return _caps_item("Outliers and summary statistics",f"For the data {', '.join(map(str,values))}, which measure is less affected by the unusually large value?",f"Median ({median})",[f"Mean ({mean})",f"Range ({max(values)-min(values)})","Maximum"],"The median depends on the middle ordered value and is less affected by an extreme value than the mean.",difficulty,salt)
    if mode == 2:
        return _caps_item("Samples and populations","A school studies the reading habits of all Grade 9 learners. Which group is the population?","All Grade 9 learners at the school",["The learners selected for a survey","Only learners who read daily","The learners who returned the survey"],"The population is the entire group being studied.",difficulty,salt)
    if mode == 3:
        return _caps_item("Sources of bias","A survey about school transport is sent only to learners who use the school bus. What is the main problem?","The sample excludes learners using other transport",["The sample is too large","The responses are numerical","The survey has no question"],"The sample leaves out learners who walk, cycle or use other transport, so it may be biased.",difficulty,salt)
    if mode == 4:
        return _caps_item("Compound probability","A fair coin and a fair six-sided die are used. What is the probability of getting heads and an even number?","1/4",["1/2","1/3","1/6"],"There are 12 equally likely outcomes; heads with an even number occurs in 3, so 3/12 = 1/4.",difficulty,salt)
    trials,successes = 30 + variant * 5, 9 + variant * 2
    answer = _caps_fraction(successes,trials)
    return _caps_item("Relative frequency and probability",f"In {trials} trials, an outcome occurred {successes} times. What is the relative frequency?",answer,[_caps_fraction(successes + 1,trials),_caps_fraction(trials - successes,trials),_caps_fraction(successes,trials + 1)],f"Relative frequency = observed occurrences ÷ total trials = {successes}/{trials} = {answer}.",difficulty,salt)


def build_caps_question_seed() -> dict[str, list[dict[str, Any]]]:
    bank: dict[str, list[dict[str, Any]]] = {concept["id"]:[] for concept in CONCEPTS}
    generators = {
        "numbers":_caps_number_question,
        "patterns":_caps_patterns_question,
        "geometry":_caps_geometry_question,
        "measurement":_caps_measurement_question,
        "data":_caps_data_question,
    }
    for grade, grade_counts in CAPS_QUESTION_COUNTS.items():
        for strand_key, count in grade_counts.items():
            concept_id = f"caps_g{grade}_{strand_key}"
            for index in range(count):
                difficulty = 1 + min(2,index * 3 // count)
                salt = grade * 1_000 + index * 17 + len(strand_key)
                bank[concept_id].append(
                    generators[strand_key](grade,index,difficulty,salt)
                )
    return bank


QUESTION_SEED = build_caps_question_seed()

PROTOCOL_BLUEPRINT = {
    4: {"minutes":30,"items":24,"challenge":1,"extra":0,"blocks":[
        ("place_value","Place value and number facts","Numbers, Operations and Relationships","place_value"),
        ("add_subtract","Addition and subtraction with regrouping","Numbers, Operations and Relationships","add_subtract"),
        ("multiplication","Multiplication facts","Numbers, Operations and Relationships","multiplication"),
        ("fractions","Fractions: halves and quarters","Numbers, Operations and Relationships","basic_fractions"),
        ("patterns_measurement","Patterns and measurement","Patterns, Functions and Algebra / Measurement","patterns_measurement"),
    ]},
    5: {"minutes":30,"items":24,"challenge":1,"extra":0,"blocks":[
        ("place_value","Place value to 6 digits","Numbers, Operations and Relationships","place_value"),
        ("multiplication_division","Multiplication and division","Numbers, Operations and Relationships","multiply_divide"),
        ("fractions","Common fractions","Numbers, Operations and Relationships","fractions"),
        ("decimals","Tenths and hundredths","Numbers, Operations and Relationships","decimals"),
        ("measurement","Measurement and perimeter","Measurement","measurement"),
    ]},
    6: {"minutes":35,"items":28,"challenge":1,"extra":0,"blocks":[
        ("multiplication_division","Multiplication and division methods","Numbers, Operations and Relationships","multiply_divide"),
        ("fractions","Equivalent fractions and operations","Numbers, Operations and Relationships","fractions"),
        ("decimals","Decimal operations","Numbers, Operations and Relationships","decimals"),
        ("ratio_percentage","Early ratio and percentage","Numbers, Operations and Relationships","ratio_percent"),
        ("patterns","Number patterns","Patterns, Functions and Algebra","patterns"),
        ("measurement_data","Measurement and data handling","Measurement / Data Handling","measurement_data"),
    ]},
    7: {"minutes":40,"items":32,"challenge":1,"extra":0,"blocks":[
        ("fractions_decimals","Fractions and decimal operations","Numbers, Operations and Relationships","fractions"),
        ("percentages","Percentages","Numbers, Operations and Relationships","percentage"),
        ("integers","Integers","Numbers, Operations and Relationships","integers"),
        ("ratio_rate","Ratio and rate","Numbers, Operations and Relationships","ratio"),
        ("algebra_patterns","Algebraic patterns","Patterns, Functions and Algebra","patterns"),
        ("area_perimeter","Area and perimeter","Measurement","measurement"),
        ("data_handling","Data handling","Data Handling","data"),
    ]},
    8: {"minutes":45,"items":34,"challenge":2,"extra":1,"blocks":[
        ("integers","Integers","Numbers, Operations and Relationships","add_subtract"),
        ("fractions_decimals_percentages","Fractions, decimals and percentages","Numbers, Operations and Relationships","fractions_decimals_percentages"),
        ("exponents","Exponents and order of operations","Numbers, Operations and Relationships","exponents_order"),
        ("ratio_proportion","Ratio and proportion","Numbers, Operations and Relationships","ratio"),
        ("equations","Simple equations","Patterns, Functions and Algebra","algebra"),
        ("geometry","Geometry basics","Space and Shape","geometry"),
        ("data_handling","Data handling","Data Handling","data"),
    ]},
    9: {"minutes":45,"items":36,"challenge":1,"extra":0,"blocks":[
        ("integer_fraction_fluency","Integer and fraction fluency","Numbers, Operations and Relationships","integer_fraction"),
        ("exponents_order","Exponents and order of operations","Numbers, Operations and Relationships","exponents_order"),
        ("ratio_proportion","Ratio and proportion","Numbers, Operations and Relationships","ratio"),
        ("number_operations","Number operations","Numbers, Operations and Relationships","multiply_divide"),
        ("algebraic_expressions","Algebraic expressions","Patterns, Functions and Algebra","algebra_expression"),
        ("equations","Solving equations","Patterns, Functions and Algebra","algebra"),
        ("pythagoras_prerequisites","Pythagoras prerequisites","Space and Shape","pythagoras"),
        ("data_handling","Data handling","Data Handling","data"),
    ]},
}

PROTOCOL_STRANDS = (
    "Numbers, Operations and Relationships",
    "Patterns, Functions and Algebra",
    "Space and Shape",
    "Measurement",
    "Data Handling",
)

PROTOCOL_ERROR_CODES = {
    "C":"Conceptual gap",
    "P":"Procedural error",
    "F":"Fact recall error",
    "R":"Possible reading/language barrier",
    "N":"Not attempted / stopped by rule",
}

def _protocol_options(answer: str, candidates: list[str], seed: int) -> list[str]:
    values = [str(answer)]
    for candidate in candidates + [str(n) for n in range(0,20)]:
        candidate = str(candidate)
        if candidate not in values:
            values.append(candidate)
        if len(values) == 4:
            break
    offset = seed % len(values)
    return values[offset:] + values[:offset]

def _protocol_item_values(kind: str, grade: int, rung: int, index: int) -> tuple[str,str,list[str],str]:
    level = min(grade,max(2,grade-2+rung-1))
    if kind == "place_value":
        digits = min(6,max(2,level+1))
        leading_digit=min(9,level+1)
        number = leading_digit*10**(digits-1) + (index+3)*10**max(0,digits-3) + (rung+4)*10 + (index+1)
        place = 10 ** min(digits-1,(rung-1)*2)
        digit = (number // place) % 10
        answer = str(digit*place)
        prompt = f"What is the value of the digit {digit} in {number:,}?"
        explanation = f"The digit {digit} is in the {place:,} place, so its value is {answer}."
        return prompt,answer,[str(digit),str(place),str(digit*place+place)],explanation
    if kind == "add_subtract":
        a = (level+2)*100 + index*19 + rung*7
        b = (level+1)*13 + rung*5 + 9
        if index % 2:
            a += b
            answer = str(a-b)
            prompt = f"Calculate {a} - {b}."
        else:
            answer = str(a+b)
            prompt = f"Calculate {a} + {b}."
        explanation = f"Use place value and show each regrouping step. The result is {answer}."
        if rung == 4 and index % 2 == 0:
            prompt = f"A class collected {a} bottle tops and then collected {b} more. How many bottle tops did they collect?"
        return prompt,answer,[str(int(answer)+1),str(max(0,int(answer)-1)),str(int(answer)+10)],explanation
    if kind == "integers":
        a = level + rung + index + 2
        b = rung + index + 1
        answer = str(b-a)
        prompt = f"Calculate (-{a}) + {b}."
        explanation = f"Starting at -{a} and moving {b} units right gives {answer}."
        if rung == 4:
            prompt = f"The temperature is -{a}°C and rises by {b}°C. What is the new temperature?"
        return prompt,answer,[str(a-b),str(a+b),str(b)],explanation
    if kind == "multiply_divide":
        a = level + 4 + index
        b = 2 + (rung+index) % 9
        product = a*b
        if index % 2:
            answer = str(a)
            prompt = f"Calculate {product} ÷ {b}."
        else:
            answer = str(product)
            prompt = f"Calculate {a} × {b}."
        explanation = f"Use the related multiplication fact {a} × {b} = {product}."
        if rung == 4 and index % 2 == 0:
            prompt = f"There are {a} boxes with {b} pencils in each box. How many pencils are there?"
        return prompt,answer,[str(product+ b),str(max(0,int(answer)-b)),str(int(answer)+2)],explanation
    if kind == "multiplication":
        a = level + 4 + index
        b = 2 + (rung+index) % 9
        answer = str(a*b)
        prompt = f"Calculate {a} × {b}."
        explanation = f"Use the multiplication fact {a} × {b} = {answer}."
        if rung == 4:
            prompt = f"There are {a} boxes with {b} pencils in each box. How many pencils are there?"
        return prompt,answer,[str(a*b+b),str(max(0,a*b-b)),str(a*b+2)],explanation
    if kind == "basic_fractions":
        numerators=((1,1,4),(1,1,2),(2,1,4),(3,1,4))[rung-1]
        first,second,denominator=numerators[0],numerators[1],numerators[2]
        from fractions import Fraction
        answer=str(Fraction(first+second,denominator))
        prompt=f"Calculate {first}/{denominator} + {second}/{denominator}. Give your answer in simplest form."
        explanation=f"Add the numerators: {first+second}/{denominator}, then simplify to {answer}."
        return prompt,answer,[f"{first+second+1}/{denominator}",f"{first+second}/{denominator+1}",f"{first}/{denominator+second}"],explanation
    if kind == "fractions":
        denominator = (2,3,4,5,8,10)[(level+rung+index) % 6]
        numerator = 1 + (index % max(1,denominator-1))
        if rung % 2:
            answer=f"{numerator*2}/{denominator*2}"
            prompt=f"Which fraction is equivalent to {numerator}/{denominator}?"
            explanation=f"Multiply both numerator and denominator by 2: {answer}."
            return prompt,answer,[f"{numerator}/{denominator*2}",f"{numerator*2}/{denominator}",f"{numerator+1}/{denominator*2}"],explanation
        other = 1
        total = numerator+other
        if total >= denominator:
            numerator = 1
            total = 2
        from fractions import Fraction
        answer = str(Fraction(total,denominator))
        prompt = f"Calculate {numerator}/{denominator} + {other}/{denominator}. Give your answer in simplest form."
        explanation = f"Add the numerators: {total}/{denominator}, then simplify to {answer}."
        candidates = [f"{total+1}/{denominator}",f"{total}/{denominator+1}",f"{numerator}/{denominator+other}"]
        return prompt,answer,candidates,explanation
    if kind == "decimals":
        a = (level+index+1)*10 + rung*3
        b = (rung+index+2)*5
        total = a+b
        answer = f"{total//100}.{total%100:02d}"
        prompt = f"Calculate {a//100}.{a%100:02d} + {b//100}.{b%100:02d}."
        explanation = f"Align the decimal places before adding. The answer is {answer}."
        candidates = [f"{(total+10)//100}.{(total+10)%100:02d}",f"{max(0,total-10)//100}.{max(0,total-10)%100:02d}",f"{(a-b)//100}.{(a-b)%100:02d}"]
        if rung == 4 and index % 2 == 0:
            prompt = f"A bottle contains {a//100}.{a%100:02d} L of water. Another {b//100}.{b%100:02d} L is added. How much water is there now?"
        return prompt,answer,candidates,explanation
    if kind == "ratio":
        first = 2 + (level % 3)
        second = 3 + ((rung+index)%3)
        groups = rung + 2
        first_amount = first*groups
        answer = str(second*groups)
        prompt = (
            f"A drink is mixed in the ratio {first}:{second}. If there are {first_amount} cups of the first ingredient, how many cups of the second ingredient are needed?"
            if rung==4 else f"Complete the equivalent ratio: {first}:{second} = {first_amount}:__."
        )
        explanation = f"The scale factor is {groups}, so the second amount is {second} × {groups} = {answer} cups."
        return prompt,answer,[str(int(answer)+groups),str(max(0,int(answer)-groups)),str(first_amount+second)],explanation
    if kind in {"ratio_percent","percentage"}:
        if kind=="ratio_percent" and index%2:
            return _protocol_item_values("ratio",grade,rung,index)
        base = 20 + 10*((level+rung+index)%8)
        percent = 10*((rung+index)%5+1)
        answer = str(base*percent//100)
        prompt = f"What is {percent}% of {base}?"
        explanation = f"Find one percent, then multiply by {percent}; the answer is {answer}."
        candidates = [str(base*percent//100+1),str(max(0,base*percent//100-1)),str(base+percent)]
        if rung == 4:
            prompt = f"A recipe uses {base} cups of flour. It is increased by {percent}%. How many cups of flour is that increase?"
        return prompt,answer,candidates,explanation
    if kind == "patterns":
        start = level + index + 2
        step = rung + 2
        sequence = [start + step*n for n in range(4)]
        answer = str(sequence[-1]+step)
        prompt = "Find the next number: " + ", ".join(str(n) for n in sequence) + ", __."
        explanation = f"The sequence increases by {step} each time, so the next number is {answer}."
        return prompt,answer,[str(int(answer)+step),str(int(answer)-step),str(int(answer)+1)],explanation
    if kind == "measurement":
        length = level + 4 + index
        width = rung + 2 + index
        if index % 2:
            answer = str(2*(length+width))
            prompt = f"Find the perimeter: length = {length} cm, width = {width} cm."
            explanation = f"Perimeter = 2 × ({length} + {width}) = {answer} cm."
        else:
            answer = str(length*width)
            prompt = f"Find the area: length = {length} cm, width = {width} cm."
            explanation = f"Area = length × width = {length} × {width} = {answer} cm²."
        if rung==4:
            prompt = (
                f"A rectangular garden is {length} cm long and {width} cm wide. What is its perimeter?"
                if index%2 else f"A rectangular garden is {length} cm long and {width} cm wide. What is its area?"
            )
        return prompt,answer,[str(int(answer)+length),str(max(1,int(answer)-width)),str(length+width)],explanation
    if kind == "algebra":
        coefficient = 2 + ((rung+index)%5)
        value = level + index + 3
        constant = rung + 2
        answer = str(value)
        total = coefficient*value+constant
        prompt = f"Solve {coefficient}x + {constant} = {total}."
        explanation = f"Subtract {constant}, then divide by {coefficient}; x = {answer}."
        return prompt,answer,[str(value+1),str(max(0,value-1)),str(value+coefficient)],explanation
    if kind == "algebra_expression":
        first=2+(rung%4)
        second=1+(index%3)
        answer=f"{first+second}x"
        prompt=f"Simplify {first}x + {second}x."
        explanation=f"Combine like terms: ({first} + {second})x = {answer}."
        return prompt,answer,[f"{first*second}x",f"{first+second}",f"{first+second+1}x"],explanation
    if kind == "exponents":
        base = 2 + (rung+index)%4
        exponent = 2 + (level+rung)%3
        answer = str(base**exponent)
        prompt = f"Evaluate {base}^{exponent}."
        explanation = f"{base}^{exponent} means {base} multiplied by itself {exponent} times, which is {answer}."
        return prompt,answer,[str(base*exponent),str(base**(exponent-1)),str(base**(exponent+1))],explanation
    if kind == "order_ops":
        a=level+index+2
        b=rung+2
        c=2+(index%4)
        answer=str(a+b*c)
        prompt=f"Calculate {a} + {b} × {c}."
        explanation=f"Multiply first: {b} × {c} = {b*c}; then add {a} to get {answer}."
        return prompt,answer,[str((a+b)*c),str(a*b+c),str(a+b+c)],explanation
    if kind == "geometry":
        angle = 25 + 5*((level+rung+index)%8)
        answer = str(180-angle)
        prompt = f"Two angles in a triangle are {angle}° and 90°. What is the third angle?"
        explanation = f"Angles in a triangle total 180°: 180 - 90 - {angle} = {answer}°."
        return prompt,answer,[str(90-angle),str(180+angle),str(angle)],explanation
    if kind == "pythagoras":
        a = 3 + (index%3)
        b = 4 + (rung%2)
        answer = str(a*a+b*b)
        prompt = f"Calculate {a}² + {b}²."
        if rung==4:
            prompt = f"A right-angled triangle has shorter sides {a} and {b}. What is the sum of their squares?"
        explanation = f"{a}² + {b}² = {a*a} + {b*b} = {answer}; this is a prerequisite calculation, not a full theorem test."
        return prompt,answer,[str(a+b),str(a*a+b*b+1),str(abs(a*a-b*b))],explanation
    if kind == "data":
        base=level+index
        if index%2:
            values=[base+5,base+1,base+7,base+3,base+4]
            ordered=sorted(values)
            answer=str(ordered[2])
            prompt=f"Find the median of: {', '.join(str(v) for v in values)}."
            explanation=f"Order the data; the middle value is {answer}."
            candidates=[str(ordered[1]),str(ordered[3]),str(sum(values)//len(values))]
        else:
            values=[base+1,base+3,base+4,base+6,base+11]
            mean_value=sum(values)//len(values)
            answer=str(mean_value)
            prompt=f"Find the mean of: {', '.join(str(v) for v in values)}."
            explanation=f"Add the values and divide by 5; the mean is {answer}."
            candidates=[str(mean_value+1),str(mean_value-1),str(sorted(values)[2])]
        return prompt,answer,candidates,explanation
    raise ValueError(f"Unknown protocol item type: {kind}")

def protocol_assessment_items(grade: int, form_seed: int = 0) -> list[dict]:
    blueprint = PROTOCOL_BLUEPRINT[grade]
    items = []
    for index in range(1,4):
        kind = ("place_value","add_subtract","multiply_divide")[index-1]
        prompt,answer,distractors,explanation = _protocol_item_values(kind,grade,max(1,index),index)
        item_id=f"g{grade}_warmup_{form_seed}_{index}"
        items.append({
            "id":item_id,"block_id":"warmup","block_title":"Warm-up",
            "strand":"Warm-up","kind":kind,"rung":index,"rung_grade":max(2,grade-3+index),
            "prompt":prompt,"answer":answer,            "options":_protocol_options(answer,distractors,form_seed+sum(map(ord,item_id))),
            "explanation":explanation,"warmup":True,"challenge":False,"word_problem":False,
        })
    for block_id,title,strand,kind in blueprint["blocks"]:
        for rung in range(1,5):
            item_kind = kind
            if kind == "patterns_measurement":
                item_kind = "patterns" if rung % 2 else "measurement"
            elif kind == "measurement_data":
                item_kind = "measurement" if rung % 2 else "data"
            elif kind == "fractions_decimals_percentages":
                item_kind = ("fractions","decimals","percentage","percentage")[rung-1]
            elif kind == "exponents_order":
                item_kind = "exponents" if rung % 2 else "order_ops"
            elif kind == "integer_fraction":
                item_kind = "fractions" if rung % 2 else "integers"
            prompt,answer,distractors,explanation = _protocol_item_values(item_kind,grade,rung,rung)
            word_problem = rung == 4
            if word_problem:
                if item_kind == "place_value":
                    prompt = prompt.replace("What is the value", "A learner writes the number shown. What is the value", 1)
                elif item_kind in {"fractions","basic_fractions"}:
                    expression=prompt.replace("Calculate ","",1).split(". Give",1)[0]
                    left,right=expression.split(" + ",1)
                    prompt=f"A recipe uses {left} cup of flour for one part and {right} cup for another. How much flour is needed altogether?"
                elif item_kind == "patterns":
                    sequence=prompt.replace("Find the next number: ","",1).replace(", __.","")
                    prompt=f"A repeating tile pattern has {sequence} tiles in its first four stages. How many tiles will be in the fifth stage?"
                elif item_kind == "data":
                    measure="median" if "median" in prompt else "mean"
                    scores=prompt.replace("Find the median of: ","",1).replace("Find the mean of: ","",1).rstrip(".")
                    prompt=f"Five learners' scores are {scores}. What is the {measure} score?"
                elif item_kind == "algebra":
                    equation=prompt.replace("Solve ","",1).rstrip(".")
                    left,right=equation.split(" = ",1)
                    coefficient,constant=left.split("x + ",1)
                    prompt=f"A number is multiplied by {coefficient}, then {constant} is added. The result is {right}. What is the number?"
                elif item_kind == "algebra_expression":
                    expression=prompt.replace("Simplify ","",1).rstrip(".")
                    left,right=expression.split(" + ",1)
                    prompt=f"A learner combines {left} and {right}. What is the simplified expression?"
                elif item_kind == "exponents":
                    expression=prompt.replace("Evaluate ","",1).rstrip(".")
                    base,exponent=expression.split("^",1)
                    prompt=f"A pattern starts with 1 group and multiplies by {base} at each of {exponent} stages. How many groups are there after those stages?"
                elif item_kind == "order_ops":
                    expression=prompt.replace("Calculate ","",1).rstrip(".")
                    first,product=expression.split(" + ",1)
                    packs,count=product.split(" × ",1)
                    prompt=f"A classroom has {first} counters and {packs} packs with {count} counters in each pack. How many counters are there altogether?"
                elif item_kind == "geometry":
                    prompt = "A triangle has " + prompt.replace("Two angles in a triangle are ","",1)
                elif item_kind == "measurement":
                    pass
                elif item_kind == "pythagoras":
                    pass
                elif item_kind == "multiply_divide" and not prompt.startswith("There are"):
                    prompt = "A learner works out " + prompt
                elif item_kind == "add_subtract" and not prompt.startswith("A class"):
                    prompt = "A learner works out " + prompt
                elif item_kind == "decimals" and not prompt.startswith("A bottle"):
                    prompt = "A learner works out " + prompt
                elif item_kind in {"ratio_percent","percentage"} and not prompt.startswith(("A recipe","A drink")):
                    prompt = "A learner works out " + prompt
            item_id = f"g{grade}_{block_id}_{form_seed}_{rung}"
            items.append({
                "id":item_id,"block_id":block_id,"block_title":title,"strand":strand,
                "kind":item_kind,"rung":rung,"rung_grade":min(grade,max(2,grade-2+rung-1)),
                "prompt":prompt,"answer":answer,                "options":_protocol_options(answer,distractors,form_seed+sum(map(ord,item_id))),
                "explanation":explanation,"warmup":False,"challenge":False,"word_problem":word_problem,
            })
    for index in range(1,blueprint["extra"]+1):
        kind = "multiply_divide"
        prompt,answer,distractors,explanation = _protocol_item_values(kind,grade,4,index+2)
        item_id=f"g{grade}_fluency_{form_seed}_{index}"
        items.append({
            "id":item_id,"block_id":"fluency","block_title":"Number fluency check",
            "strand":"Numbers, Operations and Relationships","kind":kind,"rung":None,
            "rung_grade":grade,"prompt":prompt,"answer":answer,
            "options":_protocol_options(answer,distractors,form_seed+sum(map(ord,item_id))),"explanation":explanation,
            "warmup":False,"challenge":False,"word_problem":False,
        })
    for index in range(1,blueprint["challenge"]+1):
        kind = ("algebra","geometry")[index-1]
        prompt,answer,distractors,explanation = _protocol_item_values(kind,grade,4,index+3)
        item_id=f"g{grade}_challenge_{form_seed}_{index}"
        items.append({
            "id":item_id,"block_id":"challenge","block_title":"Optional challenge",
            "strand":"Optional challenge","kind":kind,"rung":None,"rung_grade":grade,
            "prompt":prompt,"answer":answer,            "options":_protocol_options(answer,distractors,form_seed+sum(map(ord,item_id))),
            "explanation":explanation,"warmup":False,"challenge":True,"word_problem":False,
        })
    if len(items) != blueprint["items"]:
        raise ValueError(f"Grade {grade} blueprint expected {blueprint['items']} items, got {len(items)}")
    return items

# -----------------------------------------------------------------------------
# 2. DATABASE AND SECURITY
# -----------------------------------------------------------------------------
@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def now(): return datetime.now(timezone.utc).isoformat()

def hash_password(password: str, salt: Optional[bytes] = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return salt.hex() + ":" + digest.hex()

def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split(":", 1)
        candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1).hex()
        return hmac.compare_digest(candidate, digest_hex)
    except Exception: return False

def sign_session(payload: str) -> str:
    sig = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return payload + "." + sig

def read_session(token: Optional[str]) -> Optional[int]:
    if not token or "." not in token: return None
    payload, sig = token.rsplit(".", 1)
    expected = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected): return None
    try:
        user_id, expiry = payload.split(":", 1)
        if int(expiry) < int(time.time()): return None
        return int(user_id)
    except Exception: return None

def init_db():
    with db() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute("PRAGMA temp_store=MEMORY")
        c.execute("PRAGMA cache_size=-32768")
        c.executescript("""
        CREATE TABLE IF NOT EXISTS schools(id INTEGER PRIMARY KEY, emis_code TEXT UNIQUE NOT NULL, name TEXT NOT NULL, province TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','educator','learner')), grade INTEGER, school_name TEXT NOT NULL DEFAULT '', school_key TEXT NOT NULL DEFAULT '', province TEXT NOT NULL DEFAULT '', school_id INTEGER REFERENCES schools(id), active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS consent(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, version TEXT NOT NULL, accepted INTEGER NOT NULL, guardian_confirmed INTEGER NOT NULL DEFAULT 0, recorded_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS questions(id INTEGER PRIMARY KEY, concept_id TEXT NOT NULL, prompt TEXT NOT NULL, options_json TEXT NOT NULL, answer TEXT NOT NULL, explanation TEXT NOT NULL, difficulty INTEGER NOT NULL DEFAULT 1, active INTEGER NOT NULL DEFAULT 1, grade INTEGER, strand TEXT, topic TEXT, seed_key TEXT, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, question_id INTEGER NOT NULL REFERENCES questions(id), concept_id TEXT NOT NULL, answer TEXT NOT NULL, correct INTEGER NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS mastery(user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, concept_id TEXT NOT NULL, probability REAL NOT NULL DEFAULT 0.25, evidence INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL, PRIMARY KEY(user_id, concept_id));
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, user_id INTEGER, action TEXT NOT NULL, details TEXT, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS remedial_plans(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE, concept_ids_json TEXT NOT NULL, gap_grades INTEGER NOT NULL, catchup_terms TEXT NOT NULL, dosage TEXT NOT NULL, target TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS remedial_exercises(id INTEGER PRIMARY KEY, plan_id INTEGER NOT NULL REFERENCES remedial_plans(id) ON DELETE CASCADE, exercise_key TEXT NOT NULL, title TEXT NOT NULL, instructions TEXT NOT NULL, required INTEGER NOT NULL DEFAULT 1, completed INTEGER NOT NULL DEFAULT 0, completed_at TEXT, UNIQUE(plan_id,exercise_key));
        CREATE TABLE IF NOT EXISTS protocol_sittings(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, grade INTEGER NOT NULL, target_minutes INTEGER NOT NULL, status TEXT NOT NULL CHECK(status IN ('in_progress','completed')), started_at TEXT NOT NULL, completed_at TEXT, items_json TEXT NOT NULL, answers_json TEXT, results_json TEXT, reflection_json TEXT);
        CREATE INDEX IF NOT EXISTS idx_attempt_user ON attempts(user_id);
        CREATE INDEX IF NOT EXISTS idx_attempt_user_question ON attempts(user_id,question_id);
        CREATE INDEX IF NOT EXISTS idx_consent_user_latest ON consent(user_id,id DESC);
        CREATE INDEX IF NOT EXISTS idx_question_concept ON questions(concept_id);
        CREATE INDEX IF NOT EXISTS idx_protocol_user ON protocol_sittings(user_id,started_at);
        CREATE INDEX IF NOT EXISTS idx_schools_province ON schools(province);
        """)
        user_columns = {row["name"] for row in c.execute("PRAGMA table_info(users)")}
        for column in ("school_name","school_key","province"):
            if column not in user_columns:
                c.execute(f"ALTER TABLE users ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
        if "school_id" not in user_columns:
            c.execute("ALTER TABLE users ADD COLUMN school_id INTEGER REFERENCES schools(id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_users_school ON users(school_id)")
        question_columns = {row["name"] for row in c.execute("PRAGMA table_info(questions)")}
        for column, definition in (
            ("grade","INTEGER"),
            ("strand","TEXT"),
            ("topic","TEXT"),
            ("seed_key","TEXT"),
        ):
            if column not in question_columns:
                c.execute(f"ALTER TABLE questions ADD COLUMN {column} {definition}")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_question_seed_key ON questions(seed_key)")
        schools_csv = os.path.join(BASE_DIR, "emis_schools.csv")
        if os.path.isfile(schools_csv):
            with open(schools_csv, "r", encoding="utf-8-sig", newline="") as source:
                for row in csv.DictReader(source):
                    emis_code = str(row.get("emis_code") or "").strip()
                    name = normalize_school_name(str(row.get("name") or ""))
                    province = str(row.get("province") or "").strip()
                    if emis_code and name and province in SOUTH_AFRICAN_PROVINCES:
                        c.execute(
                            "INSERT INTO schools(emis_code,name,province) VALUES(?,?,?) "
                            "ON CONFLICT(emis_code) DO UPDATE SET name=excluded.name,province=excluded.province",
                            (emis_code,name,province),
                        )
        for account in c.execute(
            "SELECT id,school_name,province FROM users "
            "WHERE school_id IS NULL AND school_name<>'' AND province<>''"
        ).fetchall():
            matches = c.execute(
                "SELECT id FROM schools WHERE LOWER(TRIM(name))=LOWER(TRIM(?)) AND province=?",
                (account["school_name"],account["province"]),
            ).fetchall()
            if len(matches) == 1:
                c.execute("UPDATE users SET school_id=? WHERE id=?", (matches[0]["id"],account["id"]))
        # Demo accounts are opt-in and require passwords supplied outside source code.
        if c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0 and os.environ.get("ADCOP_DEMO_ACCOUNTS","0")=="1":
            demos = [
                ("ADMIN","ADCOP Administrator","admin",None),
                ("EDUCATOR","Demo Educator","educator",None),
                ("LEARNER","Demo Learner","learner",8),
            ]
            for suffix,name,role,grade in demos:
                username = os.environ.get(f"ADCOP_DEMO_{suffix}_USERNAME","").strip().lower()
                password = os.environ.get(f"ADCOP_DEMO_{suffix}_PASSWORD","")
                if not username or not password:
                    print(f"Demo {role} account skipped: ADCOP_DEMO_{suffix}_USERNAME and ADCOP_DEMO_{suffix}_PASSWORD are required.")
                    continue
                if len(password)<12 or len(username)<3 or not username.replace("_","").isalnum():
                    print(f"Demo {role} account skipped: invalid username or password; password must contain at least 12 characters.")
                    continue
                c.execute("INSERT INTO users(username,display_name,password_hash,role,grade,created_at) VALUES(?,?,?,?,?,?)",(username,name,hash_password(password),role,grade,now()))
        current_concept_placeholders = ",".join("?" for _ in CURRENT_CONCEPT_IDS)
        c.execute(
            f"UPDATE questions SET active=0 WHERE concept_id NOT IN ({current_concept_placeholders})",
            tuple(CURRENT_CONCEPT_IDS),
        )
        current_seed_pattern = f"{CAPS_QUESTION_SEED_VERSION}:%"
        c.execute(
            "UPDATE questions SET active=0 WHERE seed_key IS NOT NULL AND seed_key NOT LIKE ?",
            (current_seed_pattern,),
        )
        for concept_id, items in QUESTION_SEED.items():
            concept = CONCEPT_BY_ID[concept_id]
            for index, item in enumerate(items):
                seed_key = f"{CAPS_QUESTION_SEED_VERSION}:{concept_id}:{index}"
                c.execute(
                    "INSERT OR IGNORE INTO questions("
                    "concept_id,prompt,options_json,answer,explanation,difficulty,active,"
                    "grade,strand,topic,seed_key,created_at"
                    ") VALUES(?,?,?,?,?,?,1,?,?,?,?,?)",
                    (
                        concept_id,
                        item["prompt"],
                        json.dumps(item["options"]),
                        item["answer"],
                        item["explanation"],
                        item["difficulty"],
                        concept["grade"],
                        concept["strand"],
                        item["topic"],
                        seed_key,
                        now(),
                    ),
                )
        # Ensure mastery rows exist for every learner/concept.
        for u in c.execute("SELECT id FROM users WHERE role='learner'").fetchall():
            for concept in CONCEPTS:
                c.execute("INSERT OR IGNORE INTO mastery(user_id,concept_id,probability,evidence,updated_at) VALUES(?,?,0.25,0,?)",(u["id"],concept["id"],now()))
        c.execute("PRAGMA user_version=4")

def audit(user_id, action, details=""):
    with db() as c: c.execute("INSERT INTO audit(user_id,action,details,created_at) VALUES(?,?,?,?)",(user_id,action,details[:500],now()))

# -----------------------------------------------------------------------------
# 3. BAYESIAN DIAGNOSTIC ENGINE
# -----------------------------------------------------------------------------
DEFAULT_PRIOR = 0.25
SLIP = 0.10       # P(wrong | mastered)
GUESS = 0.25      # P(correct | not mastered)
LEARN = 0.08      # small probability of learning between assessment items


def posterior(prior: float, correct: bool, slip: float = SLIP, guess: float = GUESS) -> float:
    """Bayesian update for a binary mastery variable with slip and guess."""
    p = min(max(float(prior), 1e-6), 1-1e-6)
    likelihood_mastered = (1-slip) if correct else slip
    likelihood_unmastered = guess if correct else (1-guess)
    denominator = p*likelihood_mastered + (1-p)*likelihood_unmastered
    updated = (p*likelihood_mastered/denominator) if denominator else p
    return min(max(updated, 0.001), 0.999)


def propagate_prerequisites(probabilities: dict[str,float]) -> dict[str,float]:
    """Conservative graph-aware adjustment; downstream mastery cannot erase gaps.

    This is a transparent heuristic, not a validated causal learning model.
    A concept's displayed estimate is discounted when its prerequisites are weak.
    The raw evidence-based posterior is retained in the database.
    """
    adjusted = dict(probabilities)
    for concept in CONCEPTS:
        prereqs = concept["prerequisites"]
        if prereqs:
            weakest = min(probabilities.get(p, DEFAULT_PRIOR) for p in prereqs)
            raw = probabilities.get(concept["id"], DEFAULT_PRIOR)
            adjusted[concept["id"]] = min(raw, 0.65*raw + 0.35*weakest)
    return adjusted


def entropy_uncertainty(p: float) -> float:
    """Binary variance p(1-p), maximised at p=0.5."""
    return p*(1-p)


def evidence_interval(probability: float, evidence: int) -> tuple[float,float]:
    """Approximate Wilson-style uncertainty interval for a draft binary estimate.

    This is deliberately not presented as a calibrated confidence interval.
    It makes the size of the evidence set visible and prevents false precision.
    """
    n = max(0,int(evidence))
    if n == 0:
        return (0.0,1.0)
    p = min(max(float(probability),0.0),1.0)
    z = 1.96
    denominator = 1 + z*z/n
    centre = (p + z*z/(2*n))/denominator
    half_width = z*math.sqrt((p*(1-p)/n)+(z*z/(4*n*n)))/denominator
    return (
        min(max(0.0,centre-half_width),1.0),
        min(max(0.0,centre+half_width),1.0),
    )


def evidence_status(probability: float, evidence: int) -> str:
    """Conservative labels for prototype estimates with little evidence."""
    if evidence < 3:
        return "Insufficient evidence"
    low,high = evidence_interval(probability,evidence)
    if high-low >= 0.55:
        return "Needs review"
    if probability >= 0.70:
        return "Likely evidence strength"
    if probability >= 0.45:
        return "Mixed evidence"
    return "Possible gap"


def choose_next_question(user_id: int) -> Optional[dict]:
    with db() as c:
        learner = c.execute(
            "SELECT grade FROM users WHERE id=? AND role='learner' AND active=1",
            (user_id,),
        ).fetchone()
        if not learner or learner["grade"] not in range(4,10):
            return None
        learner_grade = learner["grade"]
        mastery_rows = c.execute("SELECT concept_id,probability,evidence FROM mastery WHERE user_id=?",(user_id,)).fetchall()
        attempted = {r["question_id"] for r in c.execute("SELECT question_id FROM attempts WHERE user_id=?",(user_id,)).fetchall()}
        question_rows = c.execute(
            "SELECT * FROM questions WHERE active=1 "
            "AND concept_id IN (" + ",".join("?" for _ in CONCEPTS) + ")",
            tuple(concept["id"] for concept in CONCEPTS),
        ).fetchall()
        questions_by_concept = {}
        for question in question_rows:
            questions_by_concept.setdefault(question["concept_id"], []).append(question)
        raw = {r["concept_id"]:r["probability"] for r in mastery_rows}
        adjusted = propagate_prerequisites(raw)
        candidates = []
        for concept in CONCEPTS:
            if concept["grade"] > learner_grade:
                continue
            # Prioritise concepts whose prerequisites have at least some evidence,
            # but still allow prerequisite concepts to be diagnosed first.
            prereq_readiness = min([raw.get(p,DEFAULT_PRIOR) for p in concept["prerequisites"]], default=1.0)
            score = entropy_uncertainty(adjusted.get(concept["id"],DEFAULT_PRIOR)) * (0.5 + 0.5*prereq_readiness)
            qs = questions_by_concept.get(concept["id"], [])
            available = [q for q in qs if q["id"] not in attempted]
            if available:
                # Difficulty is gradually increased as evidence of mastery increases.
                target_difficulty = 1 if raw.get(concept["id"],DEFAULT_PRIOR) < .4 else (2 if raw.get(concept["id"],DEFAULT_PRIOR) < .75 else 3)
                q = min(available, key=lambda item: abs(item["difficulty"]-target_difficulty))
                candidates.append((score, q, concept))
        if not candidates: return None
        candidates.sort(key=lambda x:(x[0], -x[1]["difficulty"]), reverse=True)
        score,q,concept = candidates[0]
        return {
            "id":q["id"],
            "concept_id":q["concept_id"],
            "concept_name":concept["name"],
            "grade":q["grade"] or concept["grade"],
            "strand":q["strand"] or concept["strand"],
            "topic":q["topic"] or "",
            "prompt":q["prompt"],
            "options":json.loads(q["options_json"]),
            "difficulty":q["difficulty"],
            "uncertainty":round(score,4),
        }


def record_answer(user_id: int, question_id: int, answer: str) -> dict:
    with db() as c:
        q = c.execute("SELECT * FROM questions WHERE id=? AND active=1",(question_id,)).fetchone()
        if not q: raise HTTPException(404,"Question not found")
        opts = json.loads(q["options_json"])
        if answer not in opts: raise HTTPException(400,"Choose one of the supplied answer options")
        already = c.execute("SELECT id FROM attempts WHERE user_id=? AND question_id=?",(user_id,question_id)).fetchone()
        if already: raise HTTPException(409,"This question has already been answered")
        correct = int(answer == q["answer"])
        row = c.execute("SELECT probability,evidence FROM mastery WHERE user_id=? AND concept_id=?",(user_id,q["concept_id"])).fetchone()
        prior = row["probability"] if row else DEFAULT_PRIOR
        updated = posterior(prior,bool(correct))
        # A small transition term represents possible learning during assessment.
        updated = updated + (1-updated)*LEARN
        updated = min(updated,0.999)
        c.execute("INSERT INTO attempts(user_id,question_id,concept_id,answer,correct,created_at) VALUES(?,?,?,?,?,?)",(user_id,question_id,q["concept_id"],answer,correct,now()))
        c.execute("INSERT INTO mastery(user_id,concept_id,probability,evidence,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(user_id,concept_id) DO UPDATE SET probability=excluded.probability,evidence=mastery.evidence+1,updated_at=excluded.updated_at",(user_id,q["concept_id"],updated,1,now()))
        return {"correct":bool(correct),"correct_answer":q["answer"],"explanation":q["explanation"],"concept_id":q["concept_id"],"posterior":round(updated,3)}

# -----------------------------------------------------------------------------
# 4. HTML UI HELPERS
# -----------------------------------------------------------------------------
CSS = """
:root{--ink:#172033;--muted:#667085;--line:#e5e9f0;--bg:#f4f6fa;--brand:#4f46e5;--good:#15803d;--warn:#b45309}
*{box-sizing:border-box}body{margin:0;background:var(--bg);font:15px/1.5 Inter,ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif;color:var(--ink)}
a{color:var(--brand);text-decoration:none}.top{background:#111827;color:white;padding:16px 5%;display:flex;justify-content:space-between;align-items:center}.brand{font-weight:800;letter-spacing:.08em}.top a{color:#e5e7eb;margin-left:16px}.wrap{max-width:1120px;margin:28px auto;padding:0 18px}.hero{background:linear-gradient(120deg,#202b49,#4f46e5);color:white;padding:28px;border-radius:18px;margin-bottom:20px}.hero h1{margin:0 0 6px;font-size:28px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:16px}.card{background:white;border:1px solid var(--line);border-radius:14px;padding:20px;box-shadow:0 3px 14px #10182808}.card h2,.card h3{margin-top:0}.muted{color:var(--muted)}.metric{font-size:30px;font-weight:800}.btn,button{display:inline-block;background:var(--brand);color:white;border:0;border-radius:9px;padding:10px 15px;font-weight:650;cursor:pointer}.btn.secondary{background:#eef2ff;color:#3730a3}.btn.danger{background:#b91c1c}input,select{width:100%;padding:11px;border:1px solid #cfd5df;border-radius:8px;margin:5px 0 13px;font:inherit}input:focus,select:focus,button:focus-visible,a:focus-visible{outline:3px solid #a5b4fc;outline-offset:2px}label{font-weight:650}fieldset.form-section{border:0;border-top:1px solid var(--line);padding:18px 0 0;margin:20px 0 0}fieldset.form-section legend{font-weight:750;padding-right:10px}.field-help{display:block;color:var(--muted);font-size:13px;margin:-8px 0 12px}.role-choice{height:100%;display:flex;flex-direction:column;align-items:flex-start;gap:12px}.role-choice .btn{margin-top:auto}.school-result{display:flex;justify-content:space-between;align-items:center;gap:16px;padding:14px 0;border-bottom:1px solid var(--line)}.school-result:last-child{border-bottom:0}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:11px;border-bottom:1px solid var(--line)}th{color:var(--muted);font-size:12px;text-transform:uppercase}.bar{height:9px;background:#edf0f5;border-radius:20px;overflow:hidden}.bar span{display:block;height:100%;background:#4f46e5}.tag{font-size:12px;background:#eef2ff;color:#3730a3;padding:3px 8px;border-radius:20px}.notice{padding:12px;background:#fffbeb;border:1px solid #fcd34d;border-radius:9px;margin:12px 0}.success{padding:12px;background:#f0fdf4;border:1px solid #86efac;border-radius:9px;margin:12px 0}.question-option{display:block;padding:12px;border:1px solid var(--line);border-radius:9px;margin:9px 0;cursor:pointer}.question-option input{width:auto;margin:0 9px 0 0}.footer{text-align:center;color:var(--muted);padding:30px;font-size:12px}@media(max-width:600px){.top{padding:14px 18px}.wrap{margin:18px auto}.hero h1{font-size:23px}.school-result{align-items:flex-start;flex-direction:column}}
.protocol-sheet{max-width:900px;margin:auto}.protocol-block{margin:18px 0;padding:20px;border:1px solid var(--line);background:#fff;border-radius:12px}.protocol-question{padding:16px 0;border-bottom:1px solid var(--line);break-inside:avoid}.protocol-question:last-child{border-bottom:0}.work-area{min-height:54px;width:100%;resize:vertical}.draft-label{display:inline-block;background:#fff7ed;color:#9a3412;border:1px solid #fdba74;border-radius:6px;padding:4px 8px;font-size:12px;font-weight:700}.error-code{max-width:360px}.status-secure{color:#166534}.status-partial{color:#92400e}.status-gap{color:#991b1b}
.chart-card{margin-top:16px}.chart-scroll{overflow-x:auto}.chart-scroll svg{display:block;width:100%;min-width:520px;height:auto}.chart-label{fill:var(--ink);font-size:13px}.chart-value{fill:var(--muted);font-size:12px;font-weight:700}.chart-track{fill:#edf0f5}.chart-bar{fill:#4f46e5}.chart-empty{color:var(--muted);padding:16px 0}
@media print{body{background:#fff;font-size:12pt}.top,.footer,.no-print,button,.btn{display:none!important}.wrap,.protocol-sheet{max-width:none;margin:0;padding:0}.hero,.card,.protocol-block{box-shadow:none;border:1px solid #999;background:#fff;color:#000;break-inside:avoid}.work-area{border:0;border-bottom:1px solid #555;min-height:60px}.protocol-question{break-inside:avoid}}
"""

def esc(value: Any) -> str:
    return html_escape(str(value), quote=True)

def bar_chart(chart_id: str, title: str, description: str, items: list[tuple[str, int]]) -> str:
    if not items:
        return (
            f'<section class="card chart-card"><h2>{esc(title)}</h2>'
            f'<p class="chart-empty">No data recorded yet.</p></section>'
        )
    max_value = max((max(0, int(value)) for _, value in items), default=0) or 1
    row_height = 38
    chart_height = 20 + row_height * len(items)
    bars = []
    for index, (label, value) in enumerate(items):
        y = 18 + index * row_height
        value = max(0, int(value))
        bar_width = round(390 * value / max_value)
        bars.append(
            f'<text class="chart-label" x="0" y="{y + 15}">{esc(label)}</text>'
            f'<rect class="chart-track" x="220" y="{y}" width="390" height="22" rx="6"></rect>'
            f'<rect class="chart-bar" x="220" y="{y}" width="{bar_width}" height="22" rx="6"></rect>'
            f'<text class="chart-value" x="{min(620, 228 + bar_width)}" y="{y + 15}">{value}</text>'
        )
    return (
        f'<section class="card chart-card"><h2>{esc(title)}</h2>'
        f'<p class="muted">{esc(description)}</p><div class="chart-scroll">'
        f'<svg viewBox="0 0 640 {chart_height}" role="img" '
        f'aria-labelledby="{esc(chart_id)}-title {esc(chart_id)}-desc">'
        f'<title id="{esc(chart_id)}-title">{esc(title)}</title>'
        f'<desc id="{esc(chart_id)}-desc">{esc(description)}</desc>'
        f'{"".join(bars)}</svg></div></section>'
    )

def csrf_token(request: Request) -> str:
    token = request.cookies.get(CSRF_COOKIE_NAME)
    if not token:
        token = secrets.token_urlsafe(32)
        request.cookies[CSRF_COOKIE_NAME] = token
    return token

def csrf_field(request: Request) -> str:
    return f'<input type="hidden" name="csrf_token" value="{esc(csrf_token(request))}">'

def csrf_ok(request: Request, submitted: str) -> bool:
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    return bool(cookie_token and submitted and hmac.compare_digest(cookie_token, submitted))

def page(title: str, body: str, user: Optional[sqlite3.Row] = None, request: Optional[Request] = None) -> HTMLResponse:
    nav = '<a href="/">Home</a>'
    if user:
        nav += '<a href="/dashboard">Dashboard</a><a href="/logout">Log out</a>'
    else: nav += '<a href="/login">Log in</a><a href="/register">Register</a>'
    html = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)} | ADCOP</title><style>{CSS}</style></head><body><header class="top"><div class="brand">ADCOP</div><nav>{nav}</nav></header><main class="wrap">{body}</main><div class="footer">ADCOP is an experimental learning-support tool. Diagnostic estimates are not formal grades or validated psychological measurements.</div></body></html>'''
    response = HTMLResponse(html)
    if request is not None:
        response.set_cookie(CSRF_COOKIE_NAME, csrf_token(request), httponly=True, samesite="strict", secure=os.environ.get("ADCOP_HTTPS","0")=="1")
    return response

def protocol_item_html(item: dict) -> str:
    options = "".join(
        f'<label class="question-option"><input type="radio" name="answer_{item["id"]}" value="{esc(option)}"> {esc(option)}</label>'
        for option in item["options"]
    )
    rung = (
        f'Grade {item["rung_grade"]} rung · Step {item["rung"]} of 4'
        if item["rung"] is not None
        else ("Optional challenge" if item["challenge"] else "Number fluency check")
    )
    marker = '<span class="tag">Word problem</span>' if item["word_problem"] else ""
    return (
        f'<article class="protocol-question"><p><b>{esc(rung)}</b> {marker}</p>'
        f'<p>{esc(item["prompt"])}</p>{options}'
        f'<label>Optional: show or explain your method<textarea class="work-area" name="method_{esc(item["id"])}" maxlength="2000"></textarea></label></article>'
    )

def protocol_assessment_body(sitting: sqlite3.Row, request: Request) -> str:
    items = json.loads(sitting["items_json"])
    warmups = [item for item in items if item["warmup"]]
    challenges = [item for item in items if item["challenge"]]
    extras = [item for item in items if item["block_id"]=="fluency"]
    blocks = []
    for block_id,title,strand in (block[:3] for block in PROTOCOL_BLUEPRINT[sitting["grade"]]["blocks"]):
        block_items = [item for item in items if item["block_id"]==block_id]
        body = "".join(protocol_item_html(item) for item in block_items)
        blocks.append(
            f'<section class="protocol-block"><h2>{esc(title)}</h2><p class="notice">Prototype ladder rule: two consecutive incorrect visible items create a need for investigation and later items are not scored as attempts. A teacher should verify this with classroom evidence.</p>{body}</section>'
        )
    extras_html = "".join(protocol_item_html(item) for item in extras)
    challenge_html = "".join(protocol_item_html(item) for item in challenges)
    reflections = []
    for index,strand in enumerate(PROTOCOL_STRANDS):
        controls = "".join(
            f'<label class="question-option"><input type="radio" name="reflection_{index}" value="{value}"> {label}</label>'
            for value,label in (("easy","Easy"),("ok","OK"),("hard","Hard"))
        )
        reflections.append(f'<fieldset class="protocol-block"><legend>{esc(strand)}</legend>{controls}</fieldset>')
    grade_spec = PROTOCOL_BLUEPRINT[sitting["grade"]]
    extras_section = f'<section class="protocol-block"><h2>Number fluency check</h2>{extras_html}</section>' if extras else ""
    challenge_section = (
        f'<section class="protocol-block"><h2>Optional challenge</h2><p>Try these if time permits; they do not count against the sub-skill scores.</p>{challenge_html}</section>'
        if challenges else ""
    )
    return (
        f'<div class="protocol-sheet"><section class="hero"><h1>Grade {sitting["grade"]} mathematics diagnostic</h1>'
        f'<p>{grade_spec["items"]} items · Suggested time: {sitting["target_minutes"]} minutes</p>'
        f'<p>Started {esc(format_assessment_time(sitting["started_at"]))}. Complete this in one sitting.</p></section>'
        '<div class="notice"><b>Draft assessment:</b> These generated questions are not CAPS-validated. Educators must review items and scoring before classroom use. '
        'Warm-up questions are not scored. On each ladder, a two-item consecutive stop is provisional and must be checked with varied classroom tasks. Answer every visible item and, where helpful, explain your method.</div>'
        f'<form method="post" action="/protocol-assessment/submit">{csrf_field(request)}'
        f'<input type="hidden" name="sitting_id" value="{sitting["id"]}">'
        f'<section class="protocol-block"><h2>Warm-up</h2><p>Confidence builders; not scored for diagnosis. Method explanations are retained for teacher discussion.</p>{"".join(protocol_item_html(item) for item in warmups)}</section>'
        f'{"".join(blocks)}'
        f'{extras_section}{challenge_section}'
        f'<section class="protocol-block"><h2>Reflection</h2><p>For each strand, select how the work felt.</p>{"".join(reflections)}</section>'
        '<button type="submit">Submit sitting and view results</button></form></div>'
    )

def current_user(request: Request):
    uid = read_session(request.cookies.get(COOKIE_NAME))
    if not uid: return None
    with db() as c: return c.execute("SELECT * FROM users WHERE id=? AND active=1",(uid,)).fetchone()

def require_user(request: Request, roles=None):
    user = current_user(request)
    if not user: raise HTTPException(303, headers={"Location":"/login"})
    if roles and user["role"] not in roles: raise HTTPException(403,"You do not have permission to access this page")
    return user

def consent_ok(user_id: int) -> bool:
    with db() as c:
        row = c.execute("SELECT accepted FROM consent WHERE user_id=? ORDER BY id DESC LIMIT 1",(user_id,)).fetchone()
        return bool(row and row["accepted"])


def normalize_school_name(value: str) -> str:
    return " ".join(value.split())


def school_key(value: str) -> str:
    return normalize_school_name(value).casefold()


def same_school(educator: sqlite3.Row, learner: sqlite3.Row) -> bool:
    if educator["role"] == "admin":
        return True
    if educator["role"] != "educator":
        return False
    if educator["school_id"] is not None and learner["school_id"] is not None:
        return educator["school_id"] == learner["school_id"]
    return bool(
        educator["school_key"]
        and educator["province"]
        and educator["school_key"] == learner["school_key"]
        and educator["province"] == learner["province"]
    )

def format_assessment_time(value: Optional[str]) -> str:
    if not value:
        return "Not recorded"
    try:
        dt = datetime.fromisoformat(value.replace("Z","+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%d %B %Y at %H:%M UTC")
    except (TypeError,ValueError):
        return "Not recorded"

def format_duration(total_seconds: int) -> str:
    total_seconds = max(0,int(total_seconds))
    hours, remainder = divmod(total_seconds,3600)
    minutes, seconds = divmod(remainder,60)
    if hours:
        return f"{hours} hr {minutes} min"
    if minutes:
        return f"{minutes} min {seconds} sec"
    return f"{seconds} sec"

def build_remedial_plan(user_id: int, report: list[dict]) -> dict:
    with db() as c:
        learner = c.execute("SELECT grade FROM users WHERE id=?", (user_id,)).fetchone()
        learner_grade = learner["grade"] if learner and learner["grade"] else 4

    focus = [item for item in report if item["evidence"] > 0 and item["probability"] < 0.55]
    if not focus:
        focus = sorted(report,key=lambda item:(item["probability"],item["grade"]))[:3]
    focus = sorted(focus,key=lambda item:(item["probability"],item["grade"]))[:3]
    concept_ids = [item["id"] for item in focus]
    names = [item["name"] for item in focus]

    current_grade = None
    for grade in range(4,10):
        cumulative = [item for item in report if item["grade"] <= grade and item["evidence"] > 0]
        evidence_at_grade = [item for item in report if item["grade"] == grade and item["evidence"] > 0]
        if evidence_at_grade and cumulative:
            average = sum(item["probability"] for item in cumulative)/len(cumulative)
            if average >= 0.70:
                current_grade = grade
            else:
                break
    # Catch-up duration cannot be inferred safely from an uncalibrated prototype.
    gap = max(1,min(learner_grade,learner_grade-(current_grade or (learner_grade-1))))
    catchup_terms = "Expert review and baseline reassessment required; no term estimate"
    dosage = (
        "Short, frequent small-group practice informed by teacher and learner needs "
        "(review after every 1 to 2 weeks)"
    )

    target = "and ".join(names)
    target += "; demonstrate the method across several representations and explain the reasoning"
    with db() as c:
        plan = c.execute("SELECT id FROM remedial_plans WHERE user_id=?", (user_id,)).fetchone()
        if plan:
            plan_id = plan["id"]
            c.execute(
                "UPDATE remedial_plans SET concept_ids_json=?,gap_grades=?,catchup_terms=?,dosage=?,target=?,updated_at=? WHERE id=?",
                (json.dumps(concept_ids),gap,catchup_terms,dosage,target,now(),plan_id),
            )
        else:
            cur = c.execute(
                "INSERT INTO remedial_plans(user_id,concept_ids_json,gap_grades,catchup_terms,dosage,target,updated_at) VALUES(?,?,?,?,?,?,?)",
                (user_id,json.dumps(concept_ids),gap,catchup_terms,dosage,target,now()),
            )
            plan_id = cur.lastrowid

        exercises = [
            (
                "warm-up",
                "Daily warm-up: secure recall",
                "For 10 minutes, practise recall facts and number strategies linked to the target. Use concrete objects or a number line first if needed.",
            ),
            (
                "show",
                "Show and explain",
                "Complete one picture or concrete-presentation task for each target. The learner must explain how they worked out the answer, not only give the result.",
            ),
            (
                "guided-practice",
                "Guided practice",
                "Complete 3 practice items with a teacher or parent nearby. Discuss any errors and repeat one corrected example for each mistake.",
            ),
            (
                "exit-check",
                "Independent practice and exit check",
                "Complete 5 independent items using the assessment question bank: " + "; ".join(names) + ". Finish with 2 exit questions and show the method. An educator compares accuracy and explanation across representations rather than applying an unsupported percentage pass mark.",
            ),
        ]
        for key,title,instructions in exercises:
            c.execute(
                "INSERT INTO remedial_exercises(plan_id,exercise_key,title,instructions,required,completed,completed_at) VALUES(?,?,?,?,1,0,NULL) ON CONFLICT(plan_id,exercise_key) DO UPDATE SET title=excluded.title,instructions=excluded.instructions,required=1",
                (plan_id,key,title,instructions),
            )
        plan_row = c.execute("SELECT * FROM remedial_plans WHERE id=?", (plan_id,)).fetchone()
        exercise_rows = c.execute(
            "SELECT id,exercise_key,title,instructions,required,completed,completed_at FROM remedial_exercises WHERE plan_id=? ORDER BY id",
            (plan_id,),
        ).fetchall()
    return {
        "id":plan_row["id"],
        "focus":[CONCEPT_BY_ID[cid] for cid in concept_ids],
        "gap_grades":plan_row["gap_grades"],
        "catchup_terms":plan_row["catchup_terms"],
        "dosage":plan_row["dosage"],
        "target":plan_row["target"],
        "exercises":[dict(row) for row in exercise_rows],
        "working_grade":min(
            (item["grade"] for item in focus if item["evidence"] > 0),
            default=None,
        ),
    }

def mastery_report(user_id: int):
    with db() as c:
        rows = c.execute("SELECT concept_id,probability,evidence FROM mastery WHERE user_id=?",(user_id,)).fetchall()
        attempts = c.execute("SELECT COUNT(*) n,COALESCE(SUM(correct),0) correct FROM attempts WHERE user_id=?",(user_id,)).fetchone()
        timing = c.execute(
            "SELECT MIN(created_at) AS started_at,MAX(created_at) AS completed_at FROM attempts WHERE user_id=?",
            (user_id,),
        ).fetchone()
    raw = {r["concept_id"]:r["probability"] for r in rows}
    evidence_by_concept = {r["concept_id"]:r["evidence"] for r in rows}
    adjusted = propagate_prerequisites(raw)
    report=[]
    for concept in CONCEPTS:
        p=adjusted.get(concept["id"],DEFAULT_PRIOR)
        evidence=evidence_by_concept.get(concept["id"],0)
        low,high=evidence_interval(p,evidence)
        status=evidence_status(p,evidence)
        report.append({
            **concept,
            "probability":p,
            "raw_probability":raw.get(concept["id"],DEFAULT_PRIOR),
            "evidence":evidence,
            "status":status,
            "uncertainty_low":low,
            "uncertainty_high":high,
        })
    # Averages of small, unvalidated concept estimates are not grade judgments.
    current_grade = None
    stats = dict(attempts)
    stats["current_grade"] = current_grade
    stats["started_at"] = timing["started_at"] if timing else None
    stats["completed_at"] = timing["completed_at"] if timing else None
    if timing and timing["started_at"] and timing["completed_at"]:
        try:
            start = datetime.fromisoformat(timing["started_at"].replace("Z","+00:00"))
            end = datetime.fromisoformat(timing["completed_at"].replace("Z","+00:00"))
            stats["duration_seconds"] = max(0,int((end-start).total_seconds()))
        except (TypeError,ValueError):
            stats["duration_seconds"] = 0
    else:
        stats["duration_seconds"] = 0
    stats["remedial_plan"] = build_remedial_plan(user_id,report)
    return report,stats

def create_protocol_sitting(user_id: int, grade: int) -> int:
    blueprint = PROTOCOL_BLUEPRINT.get(grade)
    if not blueprint:
        raise HTTPException(400,"Protocol assessments are available for Grades 4 to 9")
    form_seed = secrets.randbelow(1_000_000)
    items = protocol_assessment_items(grade, form_seed)
    with db() as c:
        active = c.execute(
            "SELECT id FROM protocol_sittings WHERE user_id=? AND status='in_progress' ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        if active:
            return active["id"]
        cur = c.execute(
            "INSERT INTO protocol_sittings(user_id,grade,target_minutes,status,started_at,items_json) VALUES(?,?,?,'in_progress',?,?)",
            (user_id,grade,blueprint["minutes"],now(),json.dumps(items)),
        )
        return cur.lastrowid

def score_protocol_sitting(items: list[dict], form: Any, grade: int) -> tuple[dict,dict,dict]:
    responses = {}
    item_results = {}
    for item in items:
        item_id = item["id"]
        answer = str(form.get(f"answer_{item_id}","")).strip()
        if answer and answer not in item["options"]:
            raise HTTPException(400,"An answer was not one of the displayed choices")
        responses[item_id] = {"answer":answer}
        item_results[item_id] = {
            "status":"correct" if answer == item["answer"] and answer else ("incorrect" if answer else "not_attempted"),
            "error_code":("N" if not answer else None),
            "answer":answer,
            "method":str(form.get(f"method_{item_id}","")).strip()[:2000],
            "rung":item["rung"],
            "rung_grade":item["rung_grade"],
            "word_problem":item["word_problem"],
        }

    block_results = []
    for block_id,title,strand in (block[:3] for block in PROTOCOL_BLUEPRINT[grade]["blocks"]):
        ladder = sorted(
            [item for item in items if item["block_id"]==block_id],
            key=lambda item:item["rung"],
        )
        wrong_in_row = 0
        first_break = None
        correct_count = 0
        for item in ladder:
            outcome = item_results[item["id"]]
            if wrong_in_row >= 2:
                outcome.update({"status":"not_attempted","error_code":"N","answer":""})
                responses[item["id"]] = {"answer":""}
                if first_break is None:
                    first_break = item["rung_grade"]
                continue
            if outcome["status"] == "correct":
                correct_count += 1
                wrong_in_row = 0
            else:
                wrong_in_row += 1
                if first_break is None:
                    first_break = item["rung_grade"]
                if outcome["status"] == "not_attempted":
                    outcome["error_code"] = "N"
        status = (
            "Secure evidence"
            if correct_count >= 3
            else ("Mixed evidence - check again" if correct_count == 2 else "Needs investigation")
        )
        block_results.append({
            "block_id":block_id,
            "title":title,
            "strand":strand,
            "correct":correct_count,
            "out_of":4,
            "status":status,
            "lowest_broken_rung":first_break,
            "items":[item["id"] for item in ladder],
        })

    reflection = {}
    for index,strand in enumerate(PROTOCOL_STRANDS):
        response = str(form.get(f"reflection_{index}","")).strip().lower()
        reflection[strand] = response if response in {"easy","ok","hard"} else ""
    result = {
        "blocks":block_results,
        "items":item_results,
        "supplementary_items":[
            {"id":item["id"],"title":item["block_title"],"status":item_results[item["id"]]["status"],"is_challenge":item["challenge"]}
            for item in items if item["block_id"]=="fluency" or item["challenge"]
        ],
        "error_codes":PROTOCOL_ERROR_CODES,
        "total_correct":sum(result["correct"] for result in block_results),
        "total_core":sum(result["out_of"] for result in block_results),
    }
    return responses,result,reflection

def protocol_worksheet_sections(sitting: sqlite3.Row) -> tuple[list[dict[str, Any]], bool]:
    """Create five fresh practice items for up to three priority sub-skills."""
    items = json.loads(sitting["items_json"])
    results = json.loads(sitting["results_json"] or "{}")
    items_by_id = {item["id"]: item for item in items}
    blocks = results.get("blocks", [])
    priorities = [
        (index, block)
        for index, block in enumerate(blocks)
        if int(block.get("correct", 0)) < 3
    ]
    general_review = not priorities
    if priorities:
        priorities.sort(key=lambda entry: (int(entry[1].get("correct", 0)), entry[0]))
        priorities = priorities[:3]
    else:
        priorities = sorted(
            enumerate(blocks),
            key=lambda entry: (int(entry[1].get("correct", 0)), entry[0]),
        )[:2]

    sections = []
    for _, block in priorities:
        ladder = sorted(
            (
                items_by_id[item_id]
                for item_id in block.get("items", [])
                if item_id in items_by_id
            ),
            key=lambda item: int(item.get("rung") or 99),
        )
        if not ladder:
            continue
        outcome_by_id = results.get("items", {})
        anchor = next(
            (
                item for item in ladder
                if outcome_by_id.get(item["id"], {}).get("status") != "correct"
            ),
            ladder[-1],
        )
        kind = anchor.get("kind")
        if not kind:
            continue
        start_rung = int(anchor.get("rung") or 1)
        questions = []
        for index in range(5):
            rung = min(4, start_rung + index // 3)
            prompt, answer, _, explanation = _protocol_item_values(
                kind,
                int(sitting["grade"]),
                rung,
                secrets.randbelow(10_000) + index,
            )
            questions.append({
                "prompt": prompt,
                "answer": answer,
                "explanation": explanation,
            })
        sections.append({
            "title": block.get("title", "Mathematics practice"),
            "correct": int(block.get("correct", 0)),
            "questions": questions,
        })
    return sections, general_review

def build_protocol_worksheet_pdf(sitting: sqlite3.Row, include_answer_key: bool) -> bytes:
    sections, general_review = protocol_worksheet_sections(sitting)
    if not sections:
        raise HTTPException(409, "No practice sections are available for this report")

    font_dir = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
    if "ADCOPVera" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("ADCOPVera", os.path.join(font_dir, "Vera.ttf")))
        pdfmetrics.registerFont(TTFont("ADCOPVera-Bold", os.path.join(font_dir, "VeraBd.ttf")))
        registerFontFamily(
            "ADCOPVera",
            normal="ADCOPVera",
            bold="ADCOPVera-Bold",
            italic="ADCOPVera",
            boldItalic="ADCOPVera-Bold",
        )

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="WorksheetTitle",
        parent=styles["Title"],
        fontName="ADCOPVera-Bold",
        fontSize=19,
        leading=24,
        textColor=colors.HexColor("#202b49"),
        alignment=TA_CENTER,
        spaceAfter=12,
    ))
    styles.add(ParagraphStyle(
        name="WorksheetHeading",
        parent=styles["Heading2"],
        fontName="ADCOPVera-Bold",
        fontSize=14,
        leading=18,
        textColor=colors.HexColor("#3730a3"),
        spaceBefore=10,
        spaceAfter=6,
        keepWithNext=True,
    ))
    styles.add(ParagraphStyle(
        name="WorksheetBody",
        parent=styles["BodyText"],
        fontName="ADCOPVera",
        fontSize=10.5,
        leading=15,
        spaceAfter=5,
    ))
    styles.add(ParagraphStyle(
        name="WorksheetSmall",
        parent=styles["BodyText"],
        fontName="ADCOPVera",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#475467"),
    ))
    styles.add(ParagraphStyle(
        name="WorksheetNotice",
        parent=styles["BodyText"],
        fontName="ADCOPVera",
        fontSize=9,
        leading=13,
        backColor=colors.HexColor("#f4f6fa"),
        borderColor=colors.HexColor("#d0d5dd"),
        borderWidth=0.5,
        borderPadding=8,
        spaceBefore=5,
        spaceAfter=10,
    ))

    document_buffer = BytesIO()
    document = SimpleDocTemplate(
        document_buffer,
        pagesize=A4,
        rightMargin=0.7 * inch,
        leftMargin=0.7 * inch,
        topMargin=0.65 * inch,
        bottomMargin=0.7 * inch,
        title=f"ADCOP Grade {sitting['grade']} Practice Worksheet",
        author="ADCOP",
    )
    worksheet_title = (
        "General Mathematics Review Worksheet"
        if general_review else "Focused Mathematics Practice Worksheet"
    )
    story = [
        Paragraph(worksheet_title, styles["WorksheetTitle"]),
        Paragraph(f"Grade {int(sitting['grade'])}", styles["WorksheetBody"]),
        Paragraph(
            f"Learner: {esc(sitting['display_name'])}    Date: ____________________",
            styles["WorksheetBody"],
        ),
        Paragraph(
            "<b>Instructions:</b> Show your working, write an answer for each question, "
            "and ask your teacher to review any step that is unclear.",
            styles["WorksheetNotice"],
        ),
    ]
    for section_number, section in enumerate(sections, start=1):
        story.append(Paragraph(
            f"{section_number}. {esc(section['title'])}",
            styles["WorksheetHeading"],
        ))
        if not general_review:
            story.append(Paragraph(
                "Selected for extra practice from the latest completed diagnostic. "
                "This is a practice guide, not a grade or diagnosis.",
                styles["WorksheetSmall"],
            ))
        for question_number, question in enumerate(section["questions"], start=1):
            story.append(KeepTogether([
                Paragraph(
                    f"<b>{question_number}.</b> {esc(question['prompt'])}",
                    styles["WorksheetBody"],
                ),
                Paragraph("Show your working:", styles["WorksheetSmall"]),
                Spacer(1, 28),
                Paragraph("Answer: ______________________________________________", styles["WorksheetSmall"]),
                Spacer(1, 8),
            ]))

    if include_answer_key:
        story.append(PageBreak())
        story.append(Paragraph("Teacher Answer Key", styles["WorksheetTitle"]))
        story.append(Paragraph(
            "Keep this page separate when giving the worksheet to a learner.",
            styles["WorksheetNotice"],
        ))
        for section in sections:
            story.append(Paragraph(esc(section["title"]), styles["WorksheetHeading"]))
            for question_number, question in enumerate(section["questions"], start=1):
                story.append(Paragraph(
                    f"<b>{question_number}. Answer:</b> {esc(question['answer'])}<br/>"
                    f"{esc(question['explanation'])}",
                    styles["WorksheetBody"],
                ))

    def draw_page_number(canvas, doc):
        canvas.saveState()
        canvas.setFont("ADCOPVera", 8)
        canvas.setFillColor(colors.HexColor("#667085"))
        canvas.drawRightString(A4[0] - doc.rightMargin, 0.4 * inch, f"Page {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=draw_page_number, onLaterPages=draw_page_number)
    return document_buffer.getvalue()

# -----------------------------------------------------------------------------
# 5. PUBLIC AND AUTHENTICATION ROUTES
# -----------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    user=current_user(request)
    body='''<section class="hero"><h1>Understand how learners understand mathematics.</h1><p>ADCOP uses a draft protocol diagnostic, exploratory Bayesian estimates and a prerequisite knowledge graph to support, not replace, teacher judgement.</p><a class="btn secondary" href="/dashboard">Open dashboard</a></section><div class="grid"><section class="card"><h3>Protocol diagnostic</h3><p class="muted">Grade-level ladders include a provisional stop-rule and optional method explanations.</p></section><section class="card"><h3>Knowledge graph</h3><p class="muted">Concept relationships remain a draft hypothesis until reviewed by curriculum specialists.</p></section><section class="card"><h3>Evidence and uncertainty</h3><p class="muted">Learners and educators see evidence counts and draft uncertainty bands, not calibrated grade scores.</p></section></div><div class="notice"><b>Research and pilot status:</b> ADCOP is a prototype. Its question bank, probability parameters and prerequisite graph require expert review and empirical validation before consequential use.</div>'''
    return page("Home",body,user)

def registration_form_body(
    request: Request,
    role: str,
    values: Optional[dict[str, str]] = None,
    error: str = "",
) -> str:
    values = values or {}
    province = values.get("province", "")
    emis_code = values.get("emis_code", "")
    display_name = values.get("display_name", "")
    username = values.get("username", "")
    grade = values.get("grade", "")
    guardian_confirmed = values.get("guardian_confirmed") == "yes"
    school_search = ""
    province_options = "".join(
        f'<option value="{esc(item)}" {"selected" if item == province else ""}>{esc(item)}</option>'
        for item in SOUTH_AFRICAN_PROVINCES
    )
    school_picker = ""
    if role == "educator":
        search_query = request.query_params.get("school_query", "").strip()[:100]
        search_province = request.query_params.get("school_search_province", "").strip()
        search_notice = ""
        search_results = ""
        if search_query:
            if len(search_query) < 2:
                search_notice = '<p class="notice" role="status">Enter at least two characters to search.</p>'
            elif search_province and search_province not in SOUTH_AFRICAN_PROVINCES:
                search_notice = '<p class="notice" role="alert">Select a valid province.</p>'
            else:
                sql = (
                    "SELECT emis_code,name,province FROM schools "
                    "WHERE (LOWER(name) LIKE ? OR emis_code LIKE ?)"
                )
                term = f"%{search_query.lower()}%"
                params: list[Any] = [term, f"%{search_query}%"]
                if search_province:
                    sql += " AND province=?"
                    params.append(search_province)
                sql += " ORDER BY name,emis_code LIMIT 20"
                with db() as c:
                    schools = c.execute(sql, tuple(params)).fetchall()
                if schools:
                    search_results = "".join(
                        f'<div class="school-result"><div><b>{esc(school["name"])}</b>'
                        f'<div class="muted">{esc(school["province"])} · EMIS {esc(school["emis_code"])}</div></div>'
                        f'<a class="btn secondary" href="/register?role=educator&amp;province={esc(school["province"])}'
                        f'&amp;emis_code={esc(school["emis_code"])}">Use this school</a></div>'
                        for school in schools
                    )
                else:
                    search_notice = '<p class="notice" role="status">No matching school found. Try another name, code or province.</p>'
        elif search_province and search_province not in SOUTH_AFRICAN_PROVINCES:
            search_notice = '<p class="notice" role="alert">Select a valid province.</p>'

        selected_school = None
        if emis_code and province in SOUTH_AFRICAN_PROVINCES:
            with db() as c:
                selected_school = c.execute(
                    "SELECT name,province FROM schools WHERE emis_code=? AND province=?",
                    (emis_code, province),
                ).fetchone()
        selected_school_note = (
            f'<p class="success" role="status">Selected school: <b>{esc(selected_school["name"])}</b>, '
            f'{esc(selected_school["province"])}.</p>'
            if selected_school
            else ""
        )
        school_search = (
            '<fieldset class="form-section"><legend>Find your school</legend>'
            '<p class="field-help">Search the official Department of Basic Education school list by name or EMIS code.</p>'
            f'<form method="get" action="/register"><input type="hidden" name="role" value="educator">'
            f'<label for="school_query">School name or EMIS code</label>'
            f'<input id="school_query" name="school_query" value="{esc(search_query)}" maxlength="100" '
            'autocomplete="off" placeholder="For example, school name or EMIS code">'
            f'<label for="school_search_province">Filter by province (optional)</label>'
            f'<select id="school_search_province" name="school_search_province"><option value="">All provinces</option>'
            + "".join(
                f'<option value="{esc(item)}" {"selected" if item == search_province else ""}>{esc(item)}</option>'
                for item in SOUTH_AFRICAN_PROVINCES
            )
            + f'</select><button class="btn secondary" type="submit">Search schools</button></form>'
            f'{search_notice}{search_results}</fieldset>'
        )
        school_picker = (
            '<fieldset class="form-section"><legend>Confirm your school</legend>'
            '<p class="field-help">Your account is linked only to the official school you select here.</p>'
            f'{selected_school_note}<label for="province">Province</label>'
            f'<select id="province" name="province" required>'
            f'<option value="">Select a province</option>{province_options}</select>'
            f'<label for="emis_code">EMIS school code</label>'
            f'<input id="emis_code" name="emis_code" value="{esc(emis_code)}" '
            'required maxlength="20" inputmode="numeric" pattern="[0-9]+" autocomplete="off">'
            '</fieldset>'
        )
    else:
        selected_grade = lambda option: "selected" if grade == option else ""
        school_picker = (
            '<fieldset class="form-section"><legend>Your school</legend>'
            '<p class="field-help">Use the official Department of Basic Education EMIS code for your school.</p>'
            f'<label for="province">Province</label><select id="province" name="province" required>'
            f'<option value="">Select a province</option>{province_options}</select>'
            f'<label for="emis_code">EMIS school code</label>'
            f'<input id="emis_code" name="emis_code" value="{esc(emis_code)}" required maxlength="20" '
            'inputmode="numeric" pattern="[0-9]+">'
            '<label for="grade">Grade</label><select id="grade" name="grade" required>'
            f'<option value="">Select a grade</option><option {selected_grade("4")}>4</option>'
            f'<option {selected_grade("5")}>5</option><option {selected_grade("6")}>6</option>'
            f'<option {selected_grade("7")}>7</option><option {selected_grade("8")}>8</option>'
            f'<option {selected_grade("9")}>9</option></select></fieldset>'
            '<label class="question-option"><input style="width:auto" type="checkbox" name="guardian_confirmed" '
            f'value="yes" {"checked" if guardian_confirmed else ""}> I am a parent/guardian or adult learner and confirm '
            'that I am authorised to create this account.</label>'
        )

    intro = (
        '<p class="muted">Request an educator account for your verified school. An administrator reviews each request; '
        'you cannot access learner information until your account is approved.</p>'
        if role == "educator"
        else '<p class="muted">Create a learner account. Assessment access starts only after the required consent step.</p>'
    )
    error_html = f'<div class="notice" role="alert">{esc(error)}</div>' if error else ""
    confirm_password = (
        '<label for="password_confirm">Confirm password</label>'
        '<input id="password_confirm" name="password_confirm" type="password" required minlength="12" '
        'autocomplete="new-password">'
        if role == "educator"
        else ""
    )
    submit_label = "Request educator access" if role == "educator" else "Create learner account"
    return (
        '<div class="card" style="max-width:680px;margin:auto">'
        f'<h1>{"Create your educator account" if role == "educator" else "Create a learner account"}</h1>'
        f'{intro}{error_html}{school_search}<form id="registration-form" method="post" action="/register">'
        f'{csrf_field(request)}<input type="hidden" name="role" value="{esc(role)}">'
        '<fieldset class="form-section"><legend>Your details</legend>'
        '<label for="display_name">Full name</label>'
        f'<input id="display_name" name="display_name" value="{esc(display_name)}" required maxlength="80" '
        'autocomplete="name">'
        '<label for="username">Username</label>'
        f'<input id="username" name="username" value="{esc(username)}" required minlength="3" maxlength="40" '
        'pattern="[A-Za-z0-9_]+" autocomplete="username" autocapitalize="none" spellcheck="false">'
        '<small class="field-help">Use 3–40 letters, numbers or underscores. You will use this to sign in.</small>'
        '<label for="password">Password</label>'
        '<input id="password" name="password" type="password" required minlength="12" autocomplete="new-password">'
        '<small class="field-help">Use at least 12 characters. Avoid reusing a password from another service.</small>'
        f'{confirm_password}</fieldset>{school_picker}'
        f'<p><button type="submit">{submit_label}</button></p></form>'
        '<p><a href="/register">Choose a different account type</a></p></div>'
    )


@app.get("/register",response_class=HTMLResponse)
def register_page(request: Request, role: Optional[str] = None):
    if role is None:
        body = (
            '<section class="hero"><h1>Choose your account type</h1>'
            '<p>Start with the account that matches how you will use ADCOP.</p></section>'
            '<div class="grid">'
            '<section class="card role-choice"><h2>Educator</h2>'
            '<p>Request access for your school. An administrator reviews educator accounts before access is enabled.</p>'
            '<a class="btn" href="/register?role=educator">Continue as an educator</a></section>'
            '<section class="card role-choice"><h2>Learner</h2>'
            '<p>Create a learner account linked to an official school. Consent is required before assessment.</p>'
            '<a class="btn secondary" href="/register?role=learner">Continue as a learner</a></section></div>'
        )
        return page("Choose account type",body,request=request)
    if role not in {"learner","educator"}:
        raise HTTPException(400,"Choose a valid account type")
    title = "Educator registration" if role == "educator" else "Learner registration"
    values = {
        key: request.query_params.get(key, "")
        for key in ("province","emis_code")
    }
    return page(title,registration_form_body(request,role,values),request=request)

@app.post("/register")
def register(
    request:Request,
    display_name:str=Form(...),
    username:str=Form(...),
    password:str=Form(...),
    role:str=Form("learner"),
    province:str=Form(...),
    emis_code:str=Form(...),
    grade:str=Form(""),
    password_confirm:str=Form(""),
    guardian_confirmed:Optional[str]=Form(None),
    csrf_token:str=Form(""),
):
    if not csrf_ok(request,csrf_token):
        raise HTTPException(403,"Invalid or expired form token")
    display_name = display_name.strip()
    username = username.strip().lower()
    emis_code = emis_code.strip()
    try:
        learner_grade = int(grade) if grade.strip() else None
    except ValueError:
        learner_grade = None

    if role not in {"learner","educator"}:
        raise HTTPException(400,"Choose a valid account type")

    values = {
        "display_name": display_name,
        "username": username,
        "province": province,
        "emis_code": emis_code,
        "grade": grade,
        "guardian_confirmed": guardian_confirmed or "",
    }

    def registration_error(message: str) -> HTMLResponse:
        title = "Educator registration" if role == "educator" else "Learner registration"
        return page(title,registration_form_body(request,role,values,message),request=request)

    if not display_name or len(display_name) > 80:
        return registration_error("Enter your full name using no more than 80 characters.")
    if (
        not 3 <= len(username) <= 40
        or not username.isascii()
        or not username.replace("_","").isalnum()
    ):
        return registration_error("Username must be 3–40 characters using letters, numbers or underscores.")
    if len(password) < 12:
        return registration_error("Choose a password with at least 12 characters.")
    if role == "educator" and password != password_confirm:
        return registration_error("The passwords do not match. Please try again.")
    if province not in SOUTH_AFRICAN_PROVINCES:
        return registration_error("Select a valid province.")
    if role == "learner" and learner_grade not in range(4,10):
        return registration_error("Select a learner grade from 4 to 9.")

    with db() as c:
        school = c.execute(
            "SELECT id,name,province FROM schools WHERE emis_code=?",
            (emis_code,),
        ).fetchone()
    if not school or school["province"] != province:
        return registration_error("Select a school and province that match an official EMIS school record.")
    school_name = school["name"]
    if not school_name or len(school_name) > 160:
        return registration_error("The selected school record is incomplete. Please choose another school.")

    active = int(role == "learner")
    with db() as c:
        try:
            cur=c.execute(
                "INSERT INTO users(username,display_name,password_hash,role,grade,school_name,school_key,province,school_id,active,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    username,
                    display_name.strip(),
                    hash_password(password),
                    role,
                    learner_grade if role=="learner" else None,
                    school_name,
                    school_key(school_name),
                    school["province"],
                    school["id"],
                    active,
                    now(),
                ),
            )
            uid=cur.lastrowid
            if role=="learner":
                c.execute("INSERT INTO consent(user_id,version,accepted,guardian_confirmed,recorded_at) VALUES(?,?,?,?,?)",(uid,"prototype-consent-v1",0,int(guardian_confirmed=="yes"),now()))
                for concept in CONCEPTS: c.execute("INSERT INTO mastery(user_id,concept_id,probability,evidence,updated_at) VALUES(?,?,0.25,0,?)",(uid,concept["id"],now()))
        except sqlite3.IntegrityError:
            return registration_error("That username is already in use. Choose another username.")
    if role=="educator":
        audit(uid,"educator_registration_pending",f"school={school_name};province={province}")
        return page(
            "Educator registration",
            '<div class="card" style="max-width:680px;margin:auto">'
            '<div class="success" role="status"><h1>Request received</h1>'
            f'<p>Your educator account request for <b>{esc(school_name)}</b>, {esc(school["province"])} is recorded.</p></div>'
            '<h2>What happens next?</h2><ol>'
            '<li>An administrator reviews your educator account and school affiliation.</li>'
            '<li>Your account remains pending until it is approved; learner information is not available before approval.</li>'
            '<li>Return to the sign-in page to check your status. It will tell you when approval is still pending.</li>'
            '</ol><a class="btn" href="/login">Go to sign in</a></div>',
        )
    token=sign_session(f"{uid}:{int(time.time())+SESSION_SECONDS}")
    response=RedirectResponse(f"/consent?uid={uid}",status_code=303)
    response.set_cookie(COOKIE_NAME,token,httponly=True,samesite="lax",secure=os.environ.get("ADCOP_HTTPS","0")=="1",max_age=SESSION_SECONDS)
    return response

@app.get("/consent",response_class=HTMLResponse)
def consent_page(request:Request,uid:int):
    user=require_user(request,["learner"])
    if user["id"] != uid: raise HTTPException(403,"You can only manage your own consent")
    body=f'''<div class="card" style="max-width:650px;margin:auto"><h2>Participation and data consent</h2><p>ADCOP stores your username, display name, grade, school name, province, assessment answers and estimated learning progress so that it can provide learning feedback. Educators may view reports only when approved for an account with the same registered school and province. Data should only be used for educational support. You may withdraw consent and request deletion.</p><p>This prototype is not a substitute for teacher judgement. Do not enter sensitive personal information.</p><div class="notice">If the learner is under 18, a parent/guardian and the responsible school must complete the appropriate consent and safeguarding process before real use. This page alone is not a legally sufficient consent process.</div><form method="post" action="/consent">{csrf_field(request)}<input type="hidden" name="uid" value="{uid}"><label><input type="checkbox" name="accept" value="yes" required style="width:auto"> I have read this notice and agree to the prototype processing described above.</label><p><button>Accept and continue</button></p></form></div>'''
    return page("Consent",body,user,request)

@app.post("/consent")
def consent_submit(request:Request,uid:int=Form(...),accept:Optional[str]=Form(None),csrf_token:str=Form("")):
    if not csrf_ok(request,csrf_token):
        raise HTTPException(403,"Invalid or expired form token")
    user=require_user(request,["learner"])
    if user["id"] != uid: raise HTTPException(403,"You can only manage your own consent")
    if accept!="yes": return RedirectResponse("/",status_code=303)
    with db() as c:
        previous = c.execute(
            "SELECT guardian_confirmed FROM consent WHERE user_id=? ORDER BY id DESC LIMIT 1",
            (uid,),
        ).fetchone()
        guardian_confirmed = int(bool(previous and previous["guardian_confirmed"]))
        c.execute(
            "INSERT INTO consent(user_id,version,accepted,guardian_confirmed,recorded_at) VALUES(?,?,?,?,?)",
            (uid,"prototype-consent-v1",1,guardian_confirmed,now()),
        )
    audit(uid,"consent_accepted","prototype-consent-v1")
    token=sign_session(f"{uid}:{int(time.time())+SESSION_SECONDS}")
    response=RedirectResponse("/dashboard",status_code=303)
    response.set_cookie(COOKIE_NAME,token,httponly=True,samesite="lax",secure=os.environ.get("ADCOP_HTTPS","0")=="1",max_age=SESSION_SECONDS)
    return response

@app.get("/login",response_class=HTMLResponse)
def login_page(request: Request):
    body=f'''<div class="card" style="max-width:480px;margin:auto"><h2>Log in</h2><form method="post" action="/login">{csrf_field(request)}<label>Username</label><input name="username" required><label>Password</label><input type="password" name="password" required><button>Log in</button></form></div>'''
    return page("Log in",body,request=request)

@app.post("/login")
def login(request:Request,username:str=Form(...),password:str=Form(...),csrf_token:str=Form("")):
    if not csrf_ok(request,csrf_token):
        raise HTTPException(403,"Invalid or expired form token")
    with db() as c: user=c.execute("SELECT * FROM users WHERE username=?",(username.strip().lower(),)).fetchone()
    if not user or not verify_password(password,user["password_hash"]): return page("Log in",'<div class="notice">Invalid username or password.</div><a href="/login">Try again</a>')
    if not user["active"]:
        if user["role"]=="educator":
            return page("Log in",'<div class="notice">Your educator account is awaiting administrator approval.</div><a href="/login">Try again</a>')
        return page("Log in",'<div class="notice">This account is disabled. Contact an administrator.</div><a href="/login">Try again</a>')
    token=sign_session(f"{user['id']}:{int(time.time())+SESSION_SECONDS}")
    destination=f"/consent?uid={user['id']}" if user["role"]=="learner" and not consent_ok(user["id"]) else "/dashboard"
    response=RedirectResponse(destination,status_code=303)
    response.set_cookie(COOKIE_NAME,token,httponly=True,samesite="lax",secure=os.environ.get("ADCOP_HTTPS","0")=="1",max_age=SESSION_SECONDS)
    audit(user["id"],"login")
    return response

@app.get("/logout")
def logout():
    response=RedirectResponse("/",status_code=303); response.delete_cookie(COOKIE_NAME); return response

# -----------------------------------------------------------------------------
# 6. DASHBOARDS
# -----------------------------------------------------------------------------
@app.get("/dashboard",response_class=HTMLResponse)
def dashboard(request:Request):
    user=require_user(request)
    if user["role"]=="learner":
        if not consent_ok(user["id"]):
            return RedirectResponse(f"/consent?uid={user['id']}",status_code=303)
        report,stats=mastery_report(user["id"])
        rows=''.join(
            f'<tr><td>{esc(x["name"])}</td><td>Grade {x["grade"]}</td>'
            f'<td>{x["uncertainty_low"]*100:.0f}–{x["uncertainty_high"]*100:.0f}%<br><small>{esc(x["status"])}</small></td>'
            f'<td>{x["evidence"]}</td></tr>'
            for x in report
        )
        evidence_count=sum(1 for x in report if x["evidence"]>0)
        body=f'''<section class="hero"><h1>Welcome, {esc(user['display_name'])}</h1><p>Your mathematics learning overview</p></section><div class="grid"><div class="card"><div class="muted">Questions answered</div><div class="metric">{stats['n']}</div></div><div class="card"><div class="muted">Correct answers</div><div class="metric">{(stats['correct']/stats['n']*100 if stats['n'] else 0):.0f}%</div></div><div class="card"><div class="muted">Concepts with evidence</div><div class="metric">{evidence_count}</div></div><div class="card"><div class="muted">Grade-level placement</div><div class="metric" style="font-size:20px">Not inferred</div></div></div><div class="notice"><b>Interpret with care:</b> prototype estimates are uncertain and are not grades, placement decisions or validated mastery probabilities.</div><div class="card" style="margin-top:16px"><h2>Adaptive assessment</h2><p class="muted">Take or retake your grade-level diagnostic. Every completed sitting creates a separate report.</p><a class="btn" href="/protocol-assessment">Open protocol diagnostic</a> <a class="btn secondary" href="/report">View full report</a></div><div class="card" style="margin-top:16px"><h2>Concept overview</h2><table><tr><th>Concept</th><th>Grade</th><th>Draft uncertainty range</th><th>Evidence</th></tr>{rows}</table></div><div class="card" style="margin-top:16px"><h3>Privacy</h3><p class="muted">You can withdraw consent and request deletion of your learner account and assessment records.</p><form method="post" action="/withdraw" onsubmit="return confirm('Withdraw consent and delete your account and learning records?')">{csrf_field(request)}<button class="danger">Withdraw consent and delete my data</button></form></div>'''
    elif user["role"]=="educator":
        with db() as c:
            if user["school_id"] is not None:
                learners=c.execute(
                    "SELECT id,display_name,username,grade FROM users "
                    "WHERE role='learner' AND active=1 AND school_id=? "
                    "AND EXISTS (SELECT 1 FROM consent c WHERE c.user_id=users.id AND c.accepted=1 "
                    "AND c.id=(SELECT MAX(c2.id) FROM consent c2 WHERE c2.user_id=users.id)) "
                    "ORDER BY display_name",
                    (user["school_id"],),
                ).fetchall()
                total=c.execute(
                    "SELECT COUNT(*) FROM attempts a JOIN users l ON l.id=a.user_id "
                    "WHERE l.role='learner' AND l.school_id=? "
                    "AND EXISTS (SELECT 1 FROM consent c WHERE c.user_id=l.id AND c.accepted=1 "
                    "AND c.id=(SELECT MAX(c2.id) FROM consent c2 WHERE c2.user_id=l.id))",
                    (user["school_id"],),
                ).fetchone()[0]
                grade_rows=c.execute(
                    "SELECT COALESCE(CAST(l.grade AS TEXT),'Grade not set') AS grade_label, "
                    "COUNT(DISTINCT l.id) AS learner_count,COUNT(a.id) AS response_count "
                    "FROM users l LEFT JOIN attempts a ON a.user_id=l.id "
                    "WHERE l.role='learner' AND l.school_id=? "
                    "AND EXISTS (SELECT 1 FROM consent c WHERE c.user_id=l.id AND c.accepted=1 "
                    "AND c.id=(SELECT MAX(c2.id) FROM consent c2 WHERE c2.user_id=l.id)) "
                    "GROUP BY l.grade ORDER BY l.grade",
                    (user["school_id"],),
                ).fetchall()
            else:
                learners=[]
                total=0
                grade_rows=[]
        rows=''.join(f'<tr><td>{esc(l["display_name"])}</td><td>{esc(l["username"])}</td><td>{l["grade"] or "—"}</td><td><a href="/educator/learner/{l["id"]}">View report</a></td></tr>' for l in learners)
        grade_learners=[(r["grade_label"] if r["grade_label"]=="Grade not set" else f'Grade {r["grade_label"]}',r["learner_count"]) for r in grade_rows]
        grade_responses=[(r["grade_label"] if r["grade_label"]=="Grade not set" else f'Grade {r["grade_label"]}',r["response_count"]) for r in grade_rows]
        educator_charts=(
            bar_chart("educator-learners-by-grade","Learners by grade","Consented learners registered at your school.",grade_learners)
            +bar_chart("educator-responses-by-grade","Responses by grade","Recorded answers from consented learners at your school.",grade_responses)
        )
        body=f'''<section class="hero"><h1>Educator dashboard</h1><p>{esc(user["school_name"])} · {esc(user["province"])}</p><p>Monitor learner progress and identify possible learning gaps.</p></section><div class="grid"><div class="card"><div class="muted">Learners at this school</div><div class="metric">{len(learners)}</div></div><div class="card"><div class="muted">School responses recorded</div><div class="metric">{total}</div></div></div>{educator_charts}<div class="card" style="margin-top:16px"><h2>Protocol diagnostics</h2><p>Review grade-level sub-skill grids and common intervention priorities for learners at your school.</p><a class="btn" href="/educator/protocol-summary">Open school protocol overview</a></div><div class="card" style="margin-top:16px"><h2>Learners at your school</h2><table><tr><th>Name</th><th>Username</th><th>Grade</th><th>Report</th></tr>{rows}</table></div><div class="notice">Use diagnostic estimates as prompts for discussion, not as high-stakes placement or grading decisions.</div>'''
    else:
        with db() as c:
            users=c.execute("SELECT id,username,display_name,role,grade,school_name,province,active FROM users ORDER BY id").fetchall()
            qcount=c.execute("SELECT COUNT(*) FROM questions WHERE active=1").fetchone()[0]
            attempts=c.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
            role_rows=c.execute(
                "SELECT role,COUNT(*) AS total FROM users GROUP BY role ORDER BY role"
            ).fetchall()
            concept_rows=c.execute(
                "SELECT concept_id,COUNT(*) AS total FROM attempts GROUP BY concept_id "
                "ORDER BY total DESC,concept_id LIMIT 8"
            ).fetchall()
        user_rows=[]
        for account in users:
            approval_action=(
                f'<form method="post" action="/admin/users/{account["id"]}/approve">'
                f'{csrf_field(request)}<button>Approve educator</button></form>'
                if account["role"]=="educator" and not account["active"]
                else ""
            )
            school_action=""
            if account["role"] in {"learner","educator"}:
                options="".join(
                    f'<option value="{esc(province)}" {"selected" if province==account["province"] else ""}>'
                    f'{esc(province)}</option>'
                    for province in SOUTH_AFRICAN_PROVINCES
                )
                school_action=(
                    f'<form method="post" action="/admin/users/{account["id"]}/school">'
                    f'{csrf_field(request)}<input name="emis_code" required maxlength="20" inputmode="numeric" '
                    'placeholder="Official EMIS code">'
                    f'<select name="province" required><option value="">Select province</option>{options}</select>'
                    '<button>Save official school</button></form>'
                )
            status="Active" if account["active"] else ("Pending approval" if account["role"]=="educator" else "Disabled")
            user_rows.append(
                f'<tr><td>{account["id"]}</td><td>{esc(account["display_name"])}</td>'
                f'<td>{esc(account["username"])}</td><td>{esc(account["role"])}</td>'
                f'<td>{account["grade"] or "—"}</td><td>{esc(account["school_name"] or "—")}</td>'
                f'<td>{esc(account["province"] or "—")}</td><td>{status}</td><td>{school_action}{approval_action}</td></tr>'
            )
        rows="".join(user_rows)
        role_labels={"admin":"Administrators","educator":"Educators","learner":"Learners"}
        role_data=[(role_labels[r["role"]],r["total"]) for r in role_rows]
        concept_data=[(CONCEPT_BY_ID[r["concept_id"]]["name"] if r["concept_id"] in CONCEPT_BY_ID else r["concept_id"],r["total"]) for r in concept_rows]
        admin_charts=(
            bar_chart("admin-accounts-by-role","Accounts by role","Number of registered accounts in each role.",role_data)
            +bar_chart("admin-responses-by-concept","Most answered concepts","Top concepts by recorded learner responses.",concept_data)
        )
        body=f'''<section class="hero"><h1>Administrator dashboard</h1><p>System overview, users and question bank.</p></section><div class="grid"><div class="card"><div class="muted">Accounts</div><div class="metric">{len(users)}</div></div><div class="card"><div class="muted">Questions</div><div class="metric">{qcount}</div></div><div class="card"><div class="muted">Responses</div><div class="metric">{attempts}</div></div><div class="card"><div class="muted">Knowledge concepts</div><div class="metric">{len(CONCEPTS)}</div></div></div>{admin_charts}<div class="card" style="margin-top:16px"><h2>Protocol report history</h2><p>Review completed diagnostic reports for learners with accepted consent.</p><a class="btn" href="/educator/protocol-summary">Open reports and class summaries</a></div><div class="card" style="margin-top:16px"><h2>Accounts</h2><table><tr><th>ID</th><th>Name</th><th>Username</th><th>Role</th><th>Grade</th><th>School</th><th>Province</th><th>Status</th><th>Action</th></tr>{rows}</table></div><div class="card" style="margin-top:16px"><h2>Question bank</h2><p><a class="btn" href="/admin/questions">Review and add questions</a> <a class="btn secondary" href="/api/knowledge-graph">View knowledge graph JSON</a></p></div>'''
    return page("Dashboard",body,user,request)

# -----------------------------------------------------------------------------
# 7. LEARNER ASSESSMENT AND REPORTS
# -----------------------------------------------------------------------------
@app.get("/assessment",response_class=HTMLResponse)
def assessment(request:Request):
    require_user(request,["learner"])
    return RedirectResponse("/protocol-assessment",status_code=303)

@app.post("/assessment/answer",response_class=HTMLResponse)
def assessment_answer(request:Request):
    require_user(request,["learner"])
    return RedirectResponse("/protocol-assessment",status_code=303)

@app.get("/report",response_class=HTMLResponse)
def learner_report(request:Request):
    user=require_user(request,["learner"])
    if not consent_ok(user["id"]):
        return RedirectResponse(f"/consent?uid={user['id']}",status_code=303)
    report,stats=mastery_report(user["id"])
    report.sort(key=lambda x:x["probability"])
    rows=''.join(
        f'<tr><td>{esc(x["name"])}</td><td>Grade {x["grade"]}</td>'
        f'<td>{x["uncertainty_low"]*100:.0f}–{x["uncertainty_high"]*100:.0f}%</td>'
        f'<td>{esc(x["status"])}</td><td>{x["evidence"]}</td></tr>'
        for x in report
    )
    weak=[x for x in report if x["evidence"] and x["probability"]<.45]
    recommendations=''.join(f'<li>Practise <b>{esc(x["name"])}</b>: revisit the concept and complete guided examples.</li>' for x in weak[:5]) or '<li>Complete more assessment questions to build stronger evidence for recommendations.</li>'
    assessment_date = format_assessment_time(stats["completed_at"])
    assessment_duration = format_duration(stats["duration_seconds"])
    plan = stats["remedial_plan"]
    working_grade = f"Grade {plan['working_grade']}" if plan["working_grade"] else "Not yet determined"
    focus_names = "".join(f"<li>{esc(item['name'])}</li>" for item in plan["focus"])
    exercise_cards = "".join(
        f'''<div class="card" style="margin:10px 0"><h3>{esc(exercise["title"])}</h3><p>{esc(exercise["instructions"])}</p><p><b>{esc("Required" if exercise["required"] else "Optional")}</b> · {esc("Completed" if exercise["completed"] else "Not completed")}</p>{f'<form method="post" action="/remedial/exercises/{exercise["id"]}/complete">{csrf_field(request)}<button type="submit">Mark complete</button></form>' if not exercise["completed"] else ''}</div>'''
        for exercise in plan["exercises"]
    )
    body=f'''<section class="hero"><h1>Your diagnostic report</h1><p>{stats['n']} responses recorded · {stats['correct']} correct</p></section><div class="notice"><b>How to interpret this report:</b> ranges are exploratory estimates from an uncalibrated question bank. They are not validated probabilities of mastery, grades or placement decisions and should be interpreted alongside classroom evidence and educator judgement.</div><div class="grid"><div class="card"><div class="muted">Grade-level placement</div><div class="metric" style="font-size:20px">Not inferred</div><small>No grade label is assigned by this prototype.</small></div><div class="card"><div class="muted">Assessment time</div><div class="metric">{assessment_duration}</div><small>Elapsed from the first to the latest recorded answer</small></div><div class="card"><div class="muted">Latest assessment completed</div><div class="metric" style="font-size:18px">{esc(assessment_date)}</div></div></div><div class="card" style="margin-top:16px"><h2>Responsive learning plan</h2><p><b>First missing or weakest skills:</b></p><ul>{focus_names}</ul><p><b>Working grade:</b> {esc(working_grade)}</p><p><b>Catch-up estimate:</b> {esc(plan["catchup_terms"])}</p><p><b>Review dosage:</b> {esc(plan["dosage"])}</p><p><b>Learning target:</b> {esc(plan["target"])}</p><p class="muted">The plan should be reviewed every 1 to 2 weeks using classroom evidence and varied re-check tasks.</p></div><div class="card" style="margin-top:16px"><h2>Required exercises</h2>{exercise_cards}</div><div class="card" style="margin-top:16px"><h2>Suggested next steps</h2><ul>{recommendations}</ul></div><div class="card" style="margin-top:16px"><h2>Estimated concept profile</h2><table><tr><th>Concept</th><th>Grade</th><th>Draft uncertainty range</th><th>Evidence</th><th>Answers</th></tr>{rows}</table></div><p><a class="btn" href="/protocol-assessment">Open protocol diagnostic</a> <a class="btn secondary" href="/dashboard">Back to dashboard</a></p>'''
    with db() as c:
        latest_protocol=c.execute(
            "SELECT id,status,grade,started_at,completed_at FROM protocol_sittings WHERE user_id=? ORDER BY started_at DESC LIMIT 1",
            (user["id"],),
        ).fetchone()
    if latest_protocol:
        protocol_href=(
            f'/protocol-report/{latest_protocol["id"]}'
            if latest_protocol["status"]=="completed"
            else "/protocol-assessment"
        )
        protocol_state="Completed" if latest_protocol["status"]=="completed" else "In progress"
        body+=(
            f'<div class="card" style="margin-top:16px"><h2>Structured Grade {latest_protocol["grade"]} diagnostic</h2>'
            f'<p>{protocol_state} · Started {esc(format_assessment_time(latest_protocol["started_at"]))}</p>'
            f'<a class="btn secondary" href="{protocol_href}">Open protocol {("report" if protocol_state=="Completed" else "sitting")}</a></div>'
        )
    return page("Diagnostic report",body,user,request)

@app.get("/protocol-assessment",response_class=HTMLResponse)
def protocol_assessment(request:Request):
    user=require_user(request,["learner"])
    if not consent_ok(user["id"]):
        return RedirectResponse(f"/consent?uid={user['id']}",status_code=303)
    with db() as c:
        sitting=c.execute(
            "SELECT * FROM protocol_sittings WHERE user_id=? AND status='in_progress' ORDER BY id DESC LIMIT 1",
            (user["id"],),
        ).fetchone()
        completed_sittings=c.execute(
            "SELECT id,grade,completed_at FROM protocol_sittings "
            "WHERE user_id=? AND status='completed' ORDER BY completed_at DESC,id DESC",
            (user["id"],),
        ).fetchall()
    history_rows="".join(
        f'<tr><td>Grade {sitting["grade"]}</td>'
        f'<td>{esc(format_assessment_time(sitting["completed_at"]))}</td>'
        f'<td><a href="/protocol-report/{sitting["id"]}">Open report</a></td></tr>'
        for sitting in completed_sittings
    )
    history_section=(
        f'<div class="card" style="margin-top:16px"><h2>Your previous diagnostic reports</h2>'
        f'<div style="overflow-x:auto"><table><tr><th>Assessment</th><th>Completed</th><th>Report</th></tr>{history_rows}</table></div></div>'
        if history_rows else ""
    )
    if sitting:
        body=protocol_assessment_body(sitting,request)+history_section
        return page("Protocol assessment",body,user,request)
    grade=user["grade"]
    if grade not in PROTOCOL_BLUEPRINT:
        raise HTTPException(400,"Your account must have a Grade 4 to 9 set for this assessment")
    blueprint=PROTOCOL_BLUEPRINT[grade]
    start_label="Start a new diagnostic sitting" if completed_sittings else "Begin diagnostic sitting"
    body=f'''<section class="hero"><h1>Grade {grade} mathematics diagnostic</h1><p>Take this diagnostic again whenever you are ready. Each completed sitting is saved as a separate dated report.</p></section><div class="notice"><b>Draft items:</b> This generated item set has not been validated by a CAPS mathematics specialist. Do not use the estimates for grades, placement, or other consequential decisions.</div><div class="notice"><b>Blueprint review:</b> The protocol's item totals and priority blocks imply more than its approximate 50–60% Numbers weighting in Grades 4–6. This draft preserves the stated counts and listed blocks; reconcile the weighting before piloting.</div><div class="card"><h2>Before you begin</h2><ul><li>{blueprint["items"]} maximum items; suggested time {blueprint["minutes"]} minutes.</li><li>Items include multiple-choice responses and an optional method explanation.</li><li>Warm-up items build confidence and are not scored.</li><li>The two-consecutive-error ladder rule is a prototype stop/needs-review signal, not a diagnosis.</li><li>Complete the end-of-sitting reflection.</li><li>The system records start and submission time. You can resume an unfinished sitting, but its elapsed time includes any pause.</li></ul><form method="post" action="/protocol-assessment/start">{csrf_field(request)}<button type="submit">{start_label}</button></form></div>{history_section}'''
    return page("Protocol assessment",body,user,request)

@app.post("/protocol-assessment/start")
def start_protocol_assessment(request:Request,csrf_token:str=Form("")):
    if not csrf_ok(request,csrf_token):
        raise HTTPException(403,"Invalid or expired form token")
    user=require_user(request,["learner"])
    if not consent_ok(user["id"]):
        raise HTTPException(403,"Consent is required")
    if user["grade"] not in PROTOCOL_BLUEPRINT:
        raise HTTPException(400,"Your account must have a Grade 4 to 9 set for this assessment")
    sitting_id=create_protocol_sitting(user["id"],user["grade"])
    audit(user["id"],"protocol_assessment_started",f"sitting_id={sitting_id};grade={user['grade']}")
    return RedirectResponse("/protocol-assessment",status_code=303)

@app.post("/protocol-assessment/submit")
async def submit_protocol_assessment(request:Request):
    form=await request.form()
    if not csrf_ok(request,str(form.get("csrf_token",""))):
        raise HTTPException(403,"Invalid or expired form token")
    user=require_user(request,["learner"])
    if not consent_ok(user["id"]):
        raise HTTPException(403,"Consent is required")
    try:
        sitting_id=int(str(form.get("sitting_id","")))
    except ValueError:
        raise HTTPException(400,"Invalid assessment sitting")
    with db() as c:
        sitting=c.execute(
            "SELECT * FROM protocol_sittings WHERE id=? AND user_id=? AND status='in_progress'",
            (sitting_id,user["id"]),
        ).fetchone()
        if not sitting:
            raise HTTPException(404,"Active assessment sitting not found")
        items=json.loads(sitting["items_json"])
        responses,results,reflection=score_protocol_sitting(items,form,sitting["grade"])
        c.execute(
            "UPDATE protocol_sittings SET status='completed',completed_at=?,answers_json=?,results_json=?,reflection_json=? WHERE id=? AND status='in_progress'",
            (now(),json.dumps(responses),json.dumps(results),json.dumps(reflection),sitting_id),
        )
    audit(user["id"],"protocol_assessment_completed",f"sitting_id={sitting_id}")
    return RedirectResponse(f"/protocol-report/{sitting_id}",status_code=303)

@app.get("/protocol-report/{sitting_id}",response_class=HTMLResponse)
def protocol_report(sitting_id:int,request:Request):
    user=require_user(request,["learner","educator","admin"])
    with db() as c:
        sitting=c.execute(
            "SELECT s.*,u.display_name,u.school_key,u.province,u.school_id FROM protocol_sittings s "
            "JOIN users u ON u.id=s.user_id WHERE s.id=?",
            (sitting_id,),
        ).fetchone()
    if not sitting:
        raise HTTPException(404,"Protocol report not found")
    if user["role"]=="learner" and user["id"]!=sitting["user_id"]:
        raise HTTPException(403,"You can only view your own assessment report")
    if user["role"]=="educator" and not same_school(user,sitting):
        raise HTTPException(403,"You can only view reports for learners at your school")
    if user["role"]=="educator" and not consent_ok(sitting["user_id"]):
        raise HTTPException(404,"Protocol report not found")
    if sitting["status"]!="completed":
        raise HTTPException(409,"This assessment has not been submitted")
    results=json.loads(sitting["results_json"] or "{}")
    reflections=json.loads(sitting["reflection_json"] or "{}")
    items=json.loads(sitting["items_json"])
    items_by_id={item["id"]:item for item in items}
    started=datetime.fromisoformat(sitting["started_at"].replace("Z","+00:00"))
    completed=datetime.fromisoformat(sitting["completed_at"].replace("Z","+00:00"))
    duration=max(0,int((completed-started).total_seconds()))
    blocks=[]
    for block in results.get("blocks",[]):
        status_class="status-secure" if block["status"]=="Secure evidence" else ("status-partial" if block["correct"]==2 else "status-gap")
        rung=(f'Grade {block["lowest_broken_rung"]}' if block["lowest_broken_rung"] else "No break recorded")
        item_details=[]
        for item_id in block["items"]:
            item=items_by_id[item_id]
            outcome=results["items"][item_id]
            if outcome["status"]=="correct":
                continue
            teacher_control=""
            if user["role"] in {"educator","admin"}:
                options = (
                    '<option value="C">C · Conceptual gap</option><option value="P">P · Procedural error</option>'
                    '<option value="F">F · Fact recall error</option><option value="R">R · Reading/language barrier</option>'
                    if outcome["status"]=="incorrect" else '<option value="N">N · Not attempted / stopped by rule</option>'
                )
                teacher_control=(
                    f'<form class="no-print" method="post" action="/educator/protocol/{sitting_id}/error-code">'
                    f'{csrf_field(request)}<input type="hidden" name="item_id" value="{esc(item_id)}">'
                    f'<select name="error_code"><option value="">Select code</option>{options}</select>'
                    f'<button type="submit">Save code</button></form>'
                )
                code_label=PROTOCOL_ERROR_CODES.get(outcome["error_code"],"Needs teacher review")
            else:
                code_label=PROTOCOL_ERROR_CODES.get(outcome["error_code"],"Needs teacher review")
            item_details.append(
                f'<li><b>Rung {item["rung"]} (Grade {item["rung_grade"]}):</b> {esc(item["prompt"])} '
                f'— {esc(outcome["status"].replace("_"," "))}; learner response: {esc(outcome["answer"] or "blank")}; '
                f'error code: {esc(code_label)}.'
                f'{("<br><b>Learner method:</b> "+esc(outcome.get("method",""))) if outcome.get("method") else ""}'
                f' {teacher_control}</li>'
            )
        details="".join(item_details) or "<p>All four ladder items were correct.</p>"
        action=(
            f"Continue with grade-level work. Review after 2 to 3 weeks."
            if block["status"]=="Secure evidence"
            else (
                f"Targeted practice from the {rung} rung, then a varied short re-check in 1 to 2 weeks."
                if block["status"]=="Mixed evidence - check again"
                else f"Teacher investigation and small-group reteaching starting at the {rung} rung; re-check in 1 to 2 weeks."
            )
        )
        required_exercise=(
            f'<p><b>Required exercise:</b> Complete five new {esc(block["title"])} problems starting at the {esc(rung)} rung. '
            'Show every method, correct any mistakes, and have a teacher check for at least 4/5 before the 2–3 week re-check.</p>'
            if block["status"]!="Secure evidence" else ""
        )
        blocks.append(
            f'<section class="protocol-block"><h3>{esc(block["title"])} · {block["correct"]}/4 '
            f'<span class="{status_class}">{esc(block["status"])}</span></h3>'
            f'<p>Lowest broken rung: {esc(rung)}. {esc(action)}</p>{required_exercise}{details}</section>'
        )
    reflection_rows="".join(
        f'<tr><td>{esc(strand)}</td><td>{esc(reflections.get(strand) or "Not recorded").title()}</td></tr>'
        for strand in PROTOCOL_STRANDS
    )
    coded_note=(
        '<p>For each incorrect item, apply one C, P, F or R code. R is a prompt to compare numerical and word-problem performance; it is not a diagnosis.</p>'
        if user["role"] in {"educator","admin"} else ""
    )
    supplementary_rows="".join(
        f'<tr><td>{esc(item["title"])}</td><td>{esc("Optional challenge" if item["is_challenge"] else "Supplementary check")}</td><td>{esc(item["status"].replace("_"," "))}</td></tr>'
        for item in results.get("supplementary_items",[])
    )
    supplementary_section=(
        f'<div class="card" style="margin-top:16px"><h2>Supplementary items</h2><table><tr><th>Item group</th><th>Type</th><th>Outcome</th></tr>{supplementary_rows}</table></div>'
        if supplementary_rows else ""
    )
    display_name=f' · {esc(sitting["display_name"])}' if user["role"]!="learner" else ""
    body=(
        f'<section class="hero"><h1>Grade {sitting["grade"]} diagnostic report{display_name}</h1>'
        f'<p>Started {esc(format_assessment_time(sitting["started_at"]))} · Submitted {esc(format_assessment_time(sitting["completed_at"]))} '
        f'· Elapsed {esc(format_duration(duration))} (suggested {sitting["target_minutes"]} min)</p></section>'
        '<div class="notice"><b>Draft diagnostic:</b> Item difficulty, curriculum alignment and generated questions need expert review. '
        'Use results as prompts for teacher investigation, not as validated mastery scores or high-stakes decisions. '
        'The written protocol’s item totals and named blocks imply more than the approximate 50–60% Numbers weighting in Grades 4–6; reconcile this blueprint before piloting.</div>'
        f'<div class="card"><h2>Sub-skill profile</h2><p>{results.get("total_correct",0)} correct across '
        f'{results.get("total_core",0)} core ladder items. Two correct out of four means “check again”, not a firm label.</p>'
        f'{"".join(blocks)}</div>{supplementary_section}{coded_note}<div class="card" style="margin-top:16px"><h2>Learner reflection</h2>'
        f'<table><tr><th>Strand</th><th>Reflection</th></tr>{reflection_rows}</table></div>'
        '<div class="card" style="margin-top:16px"><h2>Follow-up</h2><p>Group learners by shared sub-skill gaps. Review this report within 1 to 2 days, plan small-group reteaching, '
        'and re-check priority gaps with an 8 to 10 item quiz after 2 to 3 weeks or early next term.</p></div>'
    )
    worksheet_links=""
    if user["role"] in {"educator","admin"}:
        worksheet_links=(
            f'<p class="no-print"><a class="btn" href="/protocol-report/{sitting_id}/worksheet.pdf">'
            'Download practice worksheet (PDF)</a>'
            f' <a class="btn secondary" href="/protocol-report/{sitting_id}/worksheet.pdf?answer_key=true">'
            'Download worksheet with answer key (PDF)</a></p>'
        )
    body+=worksheet_links
    if user["role"]=="learner":
        body+='<p><a class="btn" href="/protocol-assessment">Start another protocol sitting</a> <a class="btn secondary" href="/dashboard">Back to dashboard</a></p>'
    else:
        body+='<p><a class="btn secondary" href="/educator/protocol-summary">Back to protocol overview</a></p>'
    return page("Protocol diagnostic report",body,user,request)

@app.get("/protocol-report/{sitting_id}/worksheet.pdf")
def protocol_worksheet(
    sitting_id:int,
    request:Request,
    answer_key:bool=False,
):
    user=require_user(request,["educator","admin"])
    with db() as c:
        sitting=c.execute(
            "SELECT s.*,u.display_name,u.school_key,u.province,u.school_id FROM protocol_sittings s "
            "JOIN users u ON u.id=s.user_id WHERE s.id=?",
            (sitting_id,),
        ).fetchone()
    if not sitting:
        raise HTTPException(404,"Protocol report not found")
    if user["role"]=="educator":
        if not same_school(user,sitting):
            raise HTTPException(403,"You can only generate worksheets for learners at your school")
        if not consent_ok(sitting["user_id"]):
            raise HTTPException(404,"Learner report not found")
    if sitting["status"]!="completed":
        raise HTTPException(409,"This assessment has not been submitted")
    pdf=build_protocol_worksheet_pdf(sitting,answer_key)
    filename=f"ADCOP_Grade_{sitting['grade']}_Practice_Worksheet"
    if answer_key:
        filename+="_Answer_Key"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition":f'attachment; filename="{filename}.pdf"',
            "Cache-Control":"private, no-store",
        },
    )

@app.post("/educator/protocol/{sitting_id}/error-code")
async def update_protocol_error_code(sitting_id:int,request:Request):
    form=await request.form()
    if not csrf_ok(request,str(form.get("csrf_token",""))):
        raise HTTPException(403,"Invalid or expired form token")
    user=require_user(request,["educator","admin"])
    item_id=str(form.get("item_id",""))
    error_code=str(form.get("error_code","")).upper()
    if error_code not in {"C","P","F","R","N"}:
        raise HTTPException(400,"Choose a valid error code")
    with db() as c:
        sitting=c.execute(
            "SELECT s.results_json,u.school_key,u.province,u.school_id FROM protocol_sittings s "
            "JOIN users u ON u.id=s.user_id WHERE s.id=? AND s.status='completed'",
            (sitting_id,),
        ).fetchone()
        if not sitting:
            raise HTTPException(404,"Completed sitting not found")
        if user["role"]=="educator" and not same_school(user,sitting):
            raise HTTPException(403,"You can only update reports for learners at your school")
        results=json.loads(sitting["results_json"] or "{}")
        outcome=results.get("items",{}).get(item_id)
        if not outcome:
            raise HTTPException(404,"Assessment item not found")
        allowed={"C","P","F","R"} if outcome["status"]=="incorrect" else {"N"} if outcome["status"]=="not_attempted" else set()
        if error_code not in allowed:
            raise HTTPException(400,"That code does not match the recorded item result")
        outcome["error_code"]=error_code
        c.execute(
            "UPDATE protocol_sittings SET results_json=? WHERE id=?",
            (json.dumps(results),sitting_id),
        )
    audit(user["id"],"protocol_error_code_recorded",f"sitting_id={sitting_id};item={item_id};code={error_code}")
    return RedirectResponse(f"/protocol-report/{sitting_id}",status_code=303)

@app.get("/educator/protocol-summary",response_class=HTMLResponse)
def educator_protocol_summary(request:Request,grade:Optional[int]=None):
    user=require_user(request,["educator","admin"])
    if grade is not None and grade not in PROTOCOL_BLUEPRINT:
        raise HTTPException(400,"Grade must be between 4 and 9")
    school_filter = ""
    school_params: tuple[Any,...] = ()
    if user["role"]=="educator":
        if user["school_id"] is not None:
            school_filter = " AND school_id=?"
            school_params = (user["school_id"],)
        else:
            school_filter = " AND 0"
    with db() as c:
        learners=c.execute(
            "SELECT id,display_name,grade FROM users WHERE role='learner' AND active=1 "
            + school_filter
            + " AND EXISTS (SELECT 1 FROM consent c WHERE c.user_id=users.id AND c.accepted=1 "
            + "AND c.id=(SELECT MAX(c2.id) FROM consent c2 WHERE c2.user_id=users.id)) "
            + ("AND grade=? " if grade is not None else "")
            + "ORDER BY grade,display_name",
            school_params + ((grade,) if grade is not None else ()),
        ).fetchall()
        sittings=c.execute(
            "SELECT s.id,s.user_id,s.grade,s.started_at,s.completed_at,s.results_json,"
            "u.display_name AS learner_name FROM protocol_sittings s "
            "JOIN users u ON u.id=s.user_id WHERE s.status='completed' "
            "AND u.role='learner' AND u.active=1 "
            + (
                "AND u.school_id=? "
                if user["role"]=="educator" and user["school_id"] is not None
                else ("AND 0 " if user["role"]=="educator" else "")
            )
            + "AND EXISTS (SELECT 1 FROM consent c WHERE c.user_id=u.id AND c.accepted=1 "
            + "AND c.id=(SELECT MAX(c2.id) FROM consent c2 WHERE c2.user_id=u.id)) "
            + ("AND s.grade=? " if grade is not None else "")
            + "ORDER BY s.completed_at DESC,s.id DESC",
            (
                (school_params if user["school_id"] is not None else ())
                if user["role"]=="educator" else ()
            ) + ((grade,) if grade is not None else ()),
        ).fetchall()
    latest={}
    for sitting in sittings:
        if sitting["user_id"] not in latest:
            latest[sitting["user_id"]]=sitting
    learner_data=[]
    counts={}
    titles={}
    for learner in learners:
        sitting=latest.get(learner["id"])
        blocks={}
        if sitting:
            results=json.loads(sitting["results_json"] or "{}")
            for block in results.get("blocks",[]):
                blocks[block["block_id"]]=block
                titles[block["block_id"]]=block["title"]
                if block["status"]=="Needs investigation":
                    counts[block["block_id"]]=counts.get(block["block_id"],0)+1
        learner_data.append((learner,sitting,blocks))
    grade_options="".join(
        f'<option value="{g}" {"selected" if grade==g else ""}>Grade {g}</option>'
        for g in PROTOCOL_BLUEPRINT
    )
    columns="".join(f"<th>{esc(titles[key])}</th>" for key in titles)
    rows=[]
    for learner,sitting,blocks in learner_data:
        if not sitting:
            cells="".join('<td class="muted">Not assessed</td>' for _ in titles)
            report_link="No completed sitting"
        else:
            cells=""
            for key in titles:
                block=blocks.get(key)
                if not block:
                    cells+='<td class="muted">—</td>'
                else:
                    cls="status-secure" if block["status"]=="Secure evidence" else ("status-partial" if block["correct"]==2 else "status-gap")
                    cells+=f'<td class="{cls}">{block["correct"]}/4 · {esc(block["status"])}</td>'
            report_link=(
                f'<a href="/protocol-report/{sitting["id"]}">View report</a><br>'
                f'<a href="/protocol-report/{sitting["id"]}/worksheet.pdf">Download worksheet (PDF)</a>'
            )
        rows.append(
            f'<tr><td>{esc(learner["display_name"])}</td><td>Grade {learner["grade"] or "—"}</td>'
            f'{cells}<td>{report_link}</td></tr>'
        )
    history_rows="".join(
        f'<tr><td>{esc(sitting["learner_name"])}</td><td>Grade {sitting["grade"]}</td>'
        f'<td>{esc(format_assessment_time(sitting["completed_at"]))}</td>'
        f'<td><a href="/protocol-report/{sitting["id"]}">Open report</a><br>'
        f'<a href="/protocol-report/{sitting["id"]}/worksheet.pdf">Download worksheet (PDF)</a></td></tr>'
        for sitting in sittings
    )
    if not history_rows:
        history_rows='<tr><td colspan="4" class="muted">No completed protocol reports yet.</td></tr>'
    top_gaps=sorted(counts.items(),key=lambda entry:(-entry[1],titles.get(entry[0],"")))[:3]
    gap_list="".join(f'<li>{esc(titles[key])}: {count} learner(s)</li>' for key,count in top_gaps)
    if not gap_list:
        gap_list="<li>No completed diagnostic gaps to summarize yet.</li>"
    body=(
        '<section class="hero"><h1>Class diagnostic overview</h1>'
        '<p>Review and group by shared sub-skill gaps within 1 to 2 days of the sitting.</p></section>'
        f'<form class="card no-print" method="get" action="/educator/protocol-summary"><label>Filter by learner grade'
        f'<select name="grade"><option value="">All grades</option>{grade_options}</select></label>'
        '<button type="submit">Apply filter</button></form>'
        f'<div class="card"><h2>Top shared gaps</h2><p>Use these counts to prioritize whole-class reteaching, then group learners by their individual gaps.</p><ol>{gap_list}</ol></div>'
        f'<div class="card" style="margin-top:16px"><h2>Latest completed sitting by learner</h2><div style="overflow-x:auto"><table><tr><th>Learner</th><th>Registered grade</th>{columns}<th>Report</th></tr>{"".join(rows)}</table></div></div>'
        f'<div class="card" style="margin-top:16px"><h2>All completed report history</h2><div style="overflow-x:auto"><table><tr><th>Learner</th><th>Assessment grade</th><th>Completed</th><th>Report and worksheet</th></tr>{history_rows}</table></div></div>'
        '<div class="notice">Sub-skill status is provisional: 3–4 correct suggests secure evidence; 2 suggests mixed evidence; 0–1 suggests a need for investigation. It is not a validated grade or placement recommendation.</div>'
    )
    return page("Class diagnostic overview",body,user,request)

# -----------------------------------------------------------------------------
# 8. EDUCATOR AND ADMIN FUNCTIONS
# -----------------------------------------------------------------------------
@app.get("/educator/learner/{learner_id}",response_class=HTMLResponse)
def educator_learner(request:Request,learner_id:int):
    user=require_user(request,["educator","admin"])
    with db() as c: learner=c.execute("SELECT * FROM users WHERE id=? AND role='learner'",(learner_id,)).fetchone()
    if not learner: raise HTTPException(404,"Learner not found")
    if user["role"]=="educator" and not same_school(user,learner):
        raise HTTPException(403,"You can only view reports for learners at your school")
    if user["role"]=="educator" and not consent_ok(learner_id):
        raise HTTPException(404,"Learner report not found")
    report,stats=mastery_report(learner_id)
    rows=''.join(
        f'<tr><td>{esc(x["name"])}</td><td>Grade {x["grade"]}</td>'
        f'<td>{x["uncertainty_low"]*100:.0f}–{x["uncertainty_high"]*100:.0f}% · {esc(x["status"])}</td>'
        f'<td>{x["evidence"]}</td></tr>'
        for x in sorted(report,key=lambda x:x["probability"])
    )
    plan = stats["remedial_plan"]
    working_grade = f"Grade {plan['working_grade']}" if plan["working_grade"] else "Not yet determined"
    completed=sum(1 for exercise in plan["exercises"] if exercise["completed"])
    exercise_rows="".join(
        f'<tr><td>{esc(exercise["title"])}</td><td>{esc("Required" if exercise["required"] else "Optional")}</td><td>{esc("Completed" if exercise["completed"] else "Not completed")}</td><td>{esc(format_assessment_time(exercise["completed_at"])) if exercise["completed"] else "—"}</td></tr>'
        for exercise in plan["exercises"]
    )
    focus_names="".join(f"<li>{esc(item['name'])}</li>" for item in plan["focus"])
    body=f'''<section class="hero"><h1>{esc(learner['display_name'])}</h1><p>Registered Grade {learner['grade'] or 'not set'} · {stats['n']} responses</p></section><div class="grid"><div class="card"><div class="muted">Grade-level placement</div><div class="metric" style="font-size:20px">Not inferred</div></div><div class="card"><div class="muted">Assessment duration</div><div class="metric">{format_duration(stats['duration_seconds'])}</div></div><div class="card"><div class="muted">Latest assessment completed</div><div class="metric" style="font-size:18px">{esc(format_assessment_time(stats['completed_at']))}</div></div></div><div class="notice">This report is educational support information. Avoid using it as the sole basis for grades, streaming, promotion or placement.</div><div class="card"><h2>Responsive learning plan</h2><p><b>First missing or weakest skills:</b></p><ul>{focus_names}</ul><p><b>Working grade:</b> {esc(working_grade)}</p><p><b>Catch-up estimate:</b> {esc(plan["catchup_terms"])}</p><p><b>Review dosage:</b> {esc(plan["dosage"])}</p><p><b>Learning target:</b> {esc(plan["target"])}</p><p><b>Exercise completion:</b> {completed} of {len(plan['exercises'])}</p></div><div class="card" style="margin-top:16px"><h2>Required exercises</h2><table><tr><th>Exercise</th><th>Type</th><th>Status</th><th>Completed</th></tr>{exercise_rows}</table></div><div class="card" style="margin-top:16px"><h2>Concept evidence</h2><table><tr><th>Concept</th><th>Grade</th><th>Draft uncertainty range and status</th><th>Evidence count</th></tr>{rows}</table></div><p><a class="btn secondary" href="/dashboard">Back</a></p>'''
    return page("Learner report",body,user,request)

@app.get("/admin/questions",response_class=HTMLResponse)
def admin_questions(request:Request):
    user=require_user(request,["admin"])
    with db() as c:
        qs=c.execute("SELECT * FROM questions WHERE active=1 ORDER BY grade,concept_id,id").fetchall()
        active_count=c.execute("SELECT COUNT(*) FROM questions WHERE active=1").fetchone()[0]
        archived_count=c.execute("SELECT COUNT(*) FROM questions WHERE active=0").fetchone()[0]
    rows=''.join(
        f'<tr><td>{q["id"]}</td><td>{esc(str(q["grade"]) if q["grade"] else "Legacy")}</td>'
        f'<td>{esc(q["strand"] or "—")}</td><td>{esc(q["topic"] or "Legacy/untagged")}</td>'
        f'<td>{esc(CONCEPT_BY_ID.get(q["concept_id"],{}).get("name",q["concept_id"]))}</td>'
        f'<td>{esc(q["prompt"])}</td><td>{q["difficulty"]}</td>'
        f'<td>{"Active" if q["active"] else "Archived"}</td></tr>'
        for q in qs
    )
    options=''.join(f'<option value="{esc(c["id"])}">{esc(c["name"])} (Grade {c["grade"]})</option>' for c in CONCEPTS)
    body=f'''<div class="card"><h2>Add a question</h2><form method="post" action="/admin/questions">{csrf_field(request)}<label>Concept</label><select name="concept_id">{options}</select><label>Topic</label><input name="topic" required maxlength="100"><label>Question</label><input name="prompt" required maxlength="500"><label>Option A</label><input name="option_a" required><label>Option B</label><input name="option_b" required><label>Option C</label><input name="option_c" required><label>Option D</label><input name="option_d" required><label>Correct option (exact text)</label><input name="answer" required><label>Explanation</label><input name="explanation" required><label>Difficulty</label><select name="difficulty"><option value="1">1 - Foundational</option><option value="2">2 - Intermediate</option><option value="3">3 - Advanced</option></select><button>Add question</button></form></div><div class="card" style="margin-top:16px"><h2>Question bank ({active_count} active; {archived_count} archived)</h2><table><tr><th>ID</th><th>Grade</th><th>Strand</th><th>Topic</th><th>Concept</th><th>Question</th><th>Level</th><th>Status</th></tr>{rows}</table></div>'''
    return page("Question bank",body,user,request)

@app.post("/admin/users/{user_id}/approve")
def approve_educator(user_id:int,request:Request,csrf_token:str=Form("")):
    if not csrf_ok(request,csrf_token):
        raise HTTPException(403,"Invalid or expired form token")
    admin=require_user(request,["admin"])
    with db() as c:
        educator=c.execute(
            "SELECT id,role,active FROM users WHERE id=?",
            (user_id,),
        ).fetchone()
        if not educator or educator["role"]!="educator":
            raise HTTPException(404,"Pending educator account not found")
        if not educator["active"]:
            c.execute("UPDATE users SET active=1 WHERE id=?",(user_id,))
    audit(admin["id"],"educator_account_approved",f"user_id={user_id}")
    return RedirectResponse("/dashboard",status_code=303)

@app.post("/admin/users/{user_id}/school")
def update_user_school(
    user_id:int,
    request:Request,
    emis_code:str=Form(...),
    province:str=Form(...),
    csrf_token:str=Form(""),
):
    if not csrf_ok(request,csrf_token):
        raise HTTPException(403,"Invalid or expired form token")
    admin=require_user(request,["admin"])
    emis_code=emis_code.strip()
    if province not in SOUTH_AFRICAN_PROVINCES:
        raise HTTPException(400,"Enter a valid province")
    with db() as c:
        account=c.execute(
            "SELECT id,role FROM users WHERE id=? AND role IN ('learner','educator')",
            (user_id,),
        ).fetchone()
        if not account:
            raise HTTPException(404,"Learner or educator account not found")
        school=c.execute(
            "SELECT id,name,province FROM schools WHERE emis_code=?",
            (emis_code,),
        ).fetchone()
        if not school or school["province"] != province:
            raise HTTPException(400,"Enter an EMIS code and province that match an official school record")
        c.execute(
            "UPDATE users SET school_name=?,school_key=?,province=?,school_id=? WHERE id=?",
            (school["name"],school_key(school["name"]),school["province"],school["id"],user_id),
        )
    audit(admin["id"],"user_school_updated",f"user_id={user_id};province={province}")
    return RedirectResponse("/dashboard",status_code=303)

@app.post("/admin/questions")
def add_question(request:Request,concept_id:str=Form(...),topic:str=Form(...),prompt:str=Form(...),option_a:str=Form(...),option_b:str=Form(...),option_c:str=Form(...),option_d:str=Form(...),answer:str=Form(...),explanation:str=Form(...),difficulty:int=Form(1),csrf_token:str=Form("")):
    if not csrf_ok(request,csrf_token):
        raise HTTPException(403,"Invalid or expired form token")
    user=require_user(request,["admin"])
    options=[option_a.strip(),option_b.strip(),option_c.strip(),option_d.strip()]
    if concept_id not in CURRENT_CONCEPT_IDS or not topic.strip() or len(set(options))!=4 or answer.strip() not in options or difficulty not in (1,2,3):
        raise HTTPException(400,"Check the concept, topic, unique options, answer and difficulty")
    concept=CONCEPT_BY_ID[concept_id]
    with db() as c:
        c.execute(
            "INSERT INTO questions(concept_id,prompt,options_json,answer,explanation,difficulty,grade,strand,topic,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                concept_id,prompt.strip(),json.dumps(options),answer.strip(),explanation.strip(),
                difficulty,concept["grade"],concept["strand"],topic.strip(),now(),
            ),
        )
    audit(user["id"],"question_added",concept_id)
    return RedirectResponse("/admin/questions",status_code=303)

@app.post("/remedial/exercises/{exercise_id}/complete")
def complete_remedial_exercise(exercise_id:int,request:Request,csrf_token:str=Form("")):
    if not csrf_ok(request,csrf_token):
        raise HTTPException(403,"Invalid or expired form token")
    user=require_user(request,["learner"])
    if not consent_ok(user["id"]):
        raise HTTPException(403,"Consent is required")
    with db() as c:
        owned = c.execute(
            "SELECT e.id FROM remedial_exercises e JOIN remedial_plans p ON p.id=e.plan_id WHERE e.id=? AND p.user_id=?",
            (exercise_id,user["id"]),
        ).fetchone()
        if not owned:
            raise HTTPException(404,"Remedial exercise not found")
        c.execute(
            "UPDATE remedial_exercises SET completed=1,completed_at=? WHERE id=?",
            (now(),exercise_id),
        )
    audit(user["id"],"remedial_exercise_completed",f"exercise_id={exercise_id}")
    return RedirectResponse("/report",status_code=303)

@app.post("/withdraw")
def withdraw(request:Request,csrf_token:str=Form("")):
    if not csrf_ok(request,csrf_token):
        raise HTTPException(403,"Invalid or expired form token")
    user=require_user(request,["learner"])
    uid=user["id"]
    audit(uid,"consent_withdrawn","Learner requested account and data deletion")
    with db() as c:
        c.execute("INSERT INTO consent(user_id,version,accepted,guardian_confirmed,recorded_at) VALUES(?,?,?,?,?)",(uid,"prototype-consent-v1",0,0,now()))
        c.execute("DELETE FROM users WHERE id=?",(uid,))
    response=RedirectResponse("/",status_code=303); response.delete_cookie(COOKIE_NAME)
    return response

# -----------------------------------------------------------------------------
# 9. API ENDPOINTS FOR FUTURE FRONTENDS / INTEGRATIONS
# -----------------------------------------------------------------------------
@app.get("/api/me")
def api_me(request:Request):
    user=require_user(request)
    return {
        "id":user["id"],
        "username":user["username"],
        "display_name":user["display_name"],
        "role":user["role"],
        "grade":user["grade"],
        "school_id":user["school_id"],
        "school_name":user["school_name"],
        "province":user["province"],
    }

@app.get("/api/knowledge-graph")
@lru_cache(maxsize=1)
def knowledge_graph():
    return {
        "concepts":CONCEPTS,
        "edges":[{"from":p,"to":c["id"]} for c in CONCEPTS for p in c["prerequisites"]],
        "archived_concepts":LEGACY_CONCEPTS,
        "note":"CAPS strand groupings and prerequisite edges are provisional hypotheses and require curriculum-specialist validation.",
    }

@app.get("/api/schools")
def list_schools(province:Optional[str]=None,q:str="",limit:int=20):
    if province and province not in SOUTH_AFRICAN_PROVINCES:
        raise HTTPException(400,"Invalid province")
    limit=max(1,min(limit,100))
    query="SELECT id,emis_code,name,province FROM schools WHERE 1=1"
    params=[]
    if province:
        query+=" AND province=?"
        params.append(province)
    if q.strip():
        query+=" AND (LOWER(name) LIKE ? OR emis_code LIKE ?)"
        term=f"%{q.strip().lower()}%"
        params.extend((term,f"%{q.strip()}%"))
    query+=" ORDER BY name,emis_code LIMIT ?"
    params.append(limit)
    with db() as c:
        rows=c.execute(query,tuple(params)).fetchall()
    return {
        "schools":[
            {"id":row["id"],"emis_code":row["emis_code"],"name":row["name"],"province":row["province"]}
            for row in rows
        ],
        "source":"South African Department of Basic Education EMIS masterlist",
    }

@app.get("/api/learner/report")
def api_report(request:Request):
    user=require_user(request,["learner"])
    if not consent_ok(user["id"]):
        raise HTTPException(403,"Consent is required")
    report,stats=mastery_report(user["id"])
    return {
        "summary":{
            **stats,
            "grade_level_not_inferred":True,
            "assessment_duration":format_duration(stats["duration_seconds"]),
            "assessment_completed_display":format_assessment_time(stats["completed_at"]),
        },
        "remedial_plan":{
            "focus_concepts":[{"id":item["id"],"name":item["name"],"grade":item["grade"]} for item in stats["remedial_plan"]["focus"]],
            "working_grade":stats["remedial_plan"]["working_grade"],
            "gap_grades":stats["remedial_plan"]["gap_grades"],
            "catch_up_window":stats["remedial_plan"]["catchup_terms"],
            "minimum_weekly_dosage":stats["remedial_plan"]["dosage"],
            "exit_target":stats["remedial_plan"]["target"],
            "exercises":[{"id":item["id"],"title":item["title"],"instructions":item["instructions"],"required":bool(item["required"]), "completed":bool(item["completed"]), "completed_at":item["completed_at"]} for item in stats["remedial_plan"]["exercises"]],
        },
        "concepts":[{
            "id":x["id"],
            "name":x["name"],
            "grade":x["grade"],
            "draft_uncertainty_range":[round(x["uncertainty_low"],4),round(x["uncertainty_high"],4)],
            "evidence_count":x["evidence"],
            "status":x["status"],
        } for x in report],
        "disclaimer":"Uncalibrated model estimates, not validated mastery scores.",
    }

@app.get("/health")
def health(): return {"status":"ok","application":"ADCOP","version":"1.0.0"}

# -----------------------------------------------------------------------------
# 10. VALIDATION UTILITIES AND DEVELOPMENT ENTRY POINT
# -----------------------------------------------------------------------------
def validate_graph() -> list[str]:
    """Return graph validation errors (unknown nodes, self-loops, cycles)."""
    errors=[]
    for c in CONCEPTS:
        for p in c["prerequisites"]:
            if p not in CONCEPT_BY_ID: errors.append(f"Unknown prerequisite {p} for {c['id']}")
            if p==c["id"]: errors.append(f"Self-loop at {p}")
    visiting=set(); visited=set()
    def visit(node):
        if node in visiting: errors.append(f"Cycle detected involving {node}"); return
        if node in visited: return
        visiting.add(node)
        for parent in CONCEPT_BY_ID.get(node,{}).get("prerequisites",[]):
            if parent in CONCEPT_BY_ID: visit(parent)
        visiting.remove(node); visited.add(node)
    for cid in CONCEPT_BY_ID: visit(cid)
    return errors

if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("ADCOP_HOST", "127.0.0.1")
    configured_port = os.environ.get("ADCOP_PORT")
    try:
        port = int(configured_port) if configured_port else 8000
        if not 1 <= port <= 65535:
            raise ValueError
    except (TypeError, ValueError):
        print("ADCOP_PORT must be an integer between 1 and 65535.")
        raise SystemExit(2)

    listen_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listen_socket.bind((host, port))
    except OSError as exc:
        listen_socket.close()
        if configured_port:
            print(f"Cannot bind ADCOP to {host}:{port}: {exc}")
            raise SystemExit(3)
        listen_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listen_socket.bind((host, 0))
            port = listen_socket.getsockname()[1]
        except OSError as exc:
            listen_socket.close()
            print(f"Cannot bind ADCOP to {host}: {exc}")
            raise SystemExit(3)
        print(f"Port 8000 on {host} is already in use; starting ADCOP on port {port}.")

    listen_socket.listen(socket.SOMAXCONN)
    print(f"Starting ADCOP at http://{host}:{port}")
    config = uvicorn.Config(app, host=host, port=port, reload=False)
    server = uvicorn.Server(config)
    server.run(sockets=[listen_socket])



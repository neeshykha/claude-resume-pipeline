"""Authoritative country stamping for the location strings the pollers assemble.

The location gates (`harvest_ats.us_reachable`, `harvest_ats.tier3_location_ok`,
`poll_ats.location_relevant`) read ONE string and decide from it whether Aneesh
could take the role. Until 2026-09-11 that string was all they had, so the only
way to recognise a non-US posting was `NON_US_MARKERS` -- a hand-maintained list
of country, region, and city names. That list is a patch over a signal several
ATSes already return per posting:

    Comeet          `location.country`              ISO alpha-2 ("CA", "IL", "JP")
    SmartRecruiters `location.country`              lowercased alpha-2 ("us")
    Ashby           `address.postalAddress.addressCountry`   name ("United States")
    Lever           `country`                       alpha-2
    Workable        `country`                       name
    Paylocity       `JobLocation.Country`           "USA"

Dropping it is what made Dot Compliance's Canadian role read "Montreal, Remote",
naming no country at all, and forced "montreal" into NON_US_MARKERS by hand.

TWO RULES SHAPE EVERYTHING HERE.

1. STAMP NON-US ONLY. A US posting's string is left byte-identical, because the
   string is not just a gate input: `poll_ats.pre_score_job` buckets on it
   (+24 atlanta / +20 remote-or-us-named / +3 otherwise) and the digest prints
   it. Appending "United States" would move every US on-site posting from the
   +3 bucket to the +20 one -- Mountain View and Meridian, ID would tie with
   remote-US -- which is the opposite of the 2026-08-02 rule that a non-Atlanta
   on-site role scores 0 on location. So a US country stamps nothing, and an
   ABSENT or unrecognised country stamps nothing either: Upwind's "Greater
   Chicago" and "Dallas-Fort Worth Metropolitan Area" postings return
   `country: ""` on a live board, so absence cannot be read as "not US".

2. TAG, DON'T APPEND A BARE NAME. The tag is `(non-US: Canada)`, matched by
   `is_non_us()`, and the three gates check it FIRST and answer outright. A bare
   appended name would have to be recognised by the free-text marker lists,
   which is the blocklist this replaces, and the codes are worse than the names:
   "CA" is California, "IL" is Illinois, "GA" is Gabon AND `ATLANTA_HINTS`
   matches ", ga". Reading the tag first also disables the dual-region rescue
   ("Remote - US or Canada" stays reachable), which is right: that rescue exists
   for free text naming two regions, and a structured per-posting country is not
   that -- Comeet duplicates a posting per location, one country each.

`GE`/`GS` are stamped as a bare code rather than a name: "Georgia" is a US state
and an ATLANTA_HINTS entry, so a Tbilisi posting stamped with its name would
read as Atlanta to any consumer that does not check the tag.
"""
import re

# ISO 3166-1 alpha-2 -> English short name, generated from
# `new Intl.DisplayNames(["en"], {type: "region"})` (CLDR), which is why a few
# exceptional reservations (AC, EU, SU, UK-as-GB) are present. Names are used
# for display only; the gate keys off the tag, not the name.
COUNTRY_NAMES = {
    "AC": "Ascension Island",
    "AD": "Andorra",
    "AE": "United Arab Emirates",
    "AF": "Afghanistan",
    "AG": "Antigua & Barbuda",
    "AI": "Anguilla",
    "AL": "Albania",
    "AM": "Armenia",
    "AN": "Curaçao",
    "AO": "Angola",
    "AQ": "Antarctica",
    "AR": "Argentina",
    "AS": "American Samoa",
    "AT": "Austria",
    "AU": "Australia",
    "AW": "Aruba",
    "AX": "Åland Islands",
    "AZ": "Azerbaijan",
    "BA": "Bosnia & Herzegovina",
    "BB": "Barbados",
    "BD": "Bangladesh",
    "BE": "Belgium",
    "BF": "Burkina Faso",
    "BG": "Bulgaria",
    "BH": "Bahrain",
    "BI": "Burundi",
    "BJ": "Benin",
    "BL": "St. Barthélemy",
    "BM": "Bermuda",
    "BN": "Brunei",
    "BO": "Bolivia",
    "BQ": "Caribbean Netherlands",
    "BR": "Brazil",
    "BS": "Bahamas",
    "BT": "Bhutan",
    "BU": "Myanmar (Burma)",
    "BV": "Bouvet Island",
    "BW": "Botswana",
    "BY": "Belarus",
    "BZ": "Belize",
    "CA": "Canada",
    "CC": "Cocos (Keeling) Islands",
    "CD": "Congo - Kinshasa",
    "CF": "Central African Republic",
    "CG": "Congo - Brazzaville",
    "CH": "Switzerland",
    "CI": "Côte d’Ivoire",
    "CK": "Cook Islands",
    "CL": "Chile",
    "CM": "Cameroon",
    "CN": "China",
    "CO": "Colombia",
    "CP": "Clipperton Island",
    "CQ": "Sark",
    "CR": "Costa Rica",
    "CS": "Serbia",
    "CU": "Cuba",
    "CV": "Cape Verde",
    "CW": "Curaçao",
    "CX": "Christmas Island",
    "CY": "Cyprus",
    "CZ": "Czechia",
    "DD": "Germany",
    "DE": "Germany",
    "DG": "Diego Garcia",
    "DJ": "Djibouti",
    "DK": "Denmark",
    "DM": "Dominica",
    "DO": "Dominican Republic",
    "DY": "Benin",
    "DZ": "Algeria",
    "EA": "Ceuta & Melilla",
    "EC": "Ecuador",
    "EE": "Estonia",
    "EG": "Egypt",
    "EH": "Western Sahara",
    "ER": "Eritrea",
    "ES": "Spain",
    "ET": "Ethiopia",
    "EU": "European Union",
    "EZ": "Eurozone",
    "FI": "Finland",
    "FJ": "Fiji",
    "FK": "Falkland Islands",
    "FM": "Micronesia",
    "FO": "Faroe Islands",
    "FR": "France",
    "FX": "France",
    "GA": "Gabon",
    "GB": "United Kingdom",
    "GD": "Grenada",
    "GE": "Georgia",
    "GF": "French Guiana",
    "GG": "Guernsey",
    "GH": "Ghana",
    "GI": "Gibraltar",
    "GL": "Greenland",
    "GM": "Gambia",
    "GN": "Guinea",
    "GP": "Guadeloupe",
    "GQ": "Equatorial Guinea",
    "GR": "Greece",
    "GS": "South Georgia & South Sandwich Islands",
    "GT": "Guatemala",
    "GU": "Guam",
    "GW": "Guinea-Bissau",
    "GY": "Guyana",
    "HK": "Hong Kong SAR China",
    "HM": "Heard & McDonald Islands",
    "HN": "Honduras",
    "HR": "Croatia",
    "HT": "Haiti",
    "HU": "Hungary",
    "HV": "Burkina Faso",
    "IC": "Canary Islands",
    "ID": "Indonesia",
    "IE": "Ireland",
    "IL": "Israel",
    "IM": "Isle of Man",
    "IN": "India",
    "IO": "British Indian Ocean Territory",
    "IQ": "Iraq",
    "IR": "Iran",
    "IS": "Iceland",
    "IT": "Italy",
    "JE": "Jersey",
    "JM": "Jamaica",
    "JO": "Jordan",
    "JP": "Japan",
    "KE": "Kenya",
    "KG": "Kyrgyzstan",
    "KH": "Cambodia",
    "KI": "Kiribati",
    "KM": "Comoros",
    "KN": "St. Kitts & Nevis",
    "KP": "North Korea",
    "KR": "South Korea",
    "KW": "Kuwait",
    "KY": "Cayman Islands",
    "KZ": "Kazakhstan",
    "LA": "Laos",
    "LB": "Lebanon",
    "LC": "St. Lucia",
    "LI": "Liechtenstein",
    "LK": "Sri Lanka",
    "LR": "Liberia",
    "LS": "Lesotho",
    "LT": "Lithuania",
    "LU": "Luxembourg",
    "LV": "Latvia",
    "LY": "Libya",
    "MA": "Morocco",
    "MC": "Monaco",
    "MD": "Moldova",
    "ME": "Montenegro",
    "MF": "St. Martin",
    "MG": "Madagascar",
    "MH": "Marshall Islands",
    "MK": "North Macedonia",
    "ML": "Mali",
    "MM": "Myanmar (Burma)",
    "MN": "Mongolia",
    "MO": "Macao SAR China",
    "MP": "Northern Mariana Islands",
    "MQ": "Martinique",
    "MR": "Mauritania",
    "MS": "Montserrat",
    "MT": "Malta",
    "MU": "Mauritius",
    "MV": "Maldives",
    "MW": "Malawi",
    "MX": "Mexico",
    "MY": "Malaysia",
    "MZ": "Mozambique",
    "NA": "Namibia",
    "NC": "New Caledonia",
    "NE": "Niger",
    "NF": "Norfolk Island",
    "NG": "Nigeria",
    "NH": "Vanuatu",
    "NI": "Nicaragua",
    "NL": "Netherlands",
    "NO": "Norway",
    "NP": "Nepal",
    "NR": "Nauru",
    "NU": "Niue",
    "NZ": "New Zealand",
    "OM": "Oman",
    "PA": "Panama",
    "PE": "Peru",
    "PF": "French Polynesia",
    "PG": "Papua New Guinea",
    "PH": "Philippines",
    "PK": "Pakistan",
    "PL": "Poland",
    "PM": "St. Pierre & Miquelon",
    "PN": "Pitcairn Islands",
    "PR": "Puerto Rico",
    "PS": "Palestinian Territories",
    "PT": "Portugal",
    "PW": "Palau",
    "PY": "Paraguay",
    "QA": "Qatar",
    "QO": "Outlying Oceania",
    "RE": "Réunion",
    "RH": "Zimbabwe",
    "RO": "Romania",
    "RS": "Serbia",
    "RU": "Russia",
    "RW": "Rwanda",
    "SA": "Saudi Arabia",
    "SB": "Solomon Islands",
    "SC": "Seychelles",
    "SD": "Sudan",
    "SE": "Sweden",
    "SG": "Singapore",
    "SH": "St. Helena",
    "SI": "Slovenia",
    "SJ": "Svalbard & Jan Mayen",
    "SK": "Slovakia",
    "SL": "Sierra Leone",
    "SM": "San Marino",
    "SN": "Senegal",
    "SO": "Somalia",
    "SR": "Suriname",
    "SS": "South Sudan",
    "ST": "São Tomé & Príncipe",
    "SU": "Russia",
    "SV": "El Salvador",
    "SX": "Sint Maarten",
    "SY": "Syria",
    "SZ": "Eswatini",
    "TA": "Tristan da Cunha",
    "TC": "Turks & Caicos Islands",
    "TD": "Chad",
    "TF": "French Southern Territories",
    "TG": "Togo",
    "TH": "Thailand",
    "TJ": "Tajikistan",
    "TK": "Tokelau",
    "TL": "Timor-Leste",
    "TM": "Turkmenistan",
    "TN": "Tunisia",
    "TO": "Tonga",
    "TP": "Timor-Leste",
    "TR": "Türkiye",
    "TT": "Trinidad & Tobago",
    "TV": "Tuvalu",
    "TW": "Taiwan",
    "TZ": "Tanzania",
    "UA": "Ukraine",
    "UG": "Uganda",
    "UK": "United Kingdom",
    "UM": "U.S. Outlying Islands",
    "UN": "United Nations",
    "US": "United States",
    "UY": "Uruguay",
    "UZ": "Uzbekistan",
    "VA": "Vatican City",
    "VC": "St. Vincent & Grenadines",
    "VD": "Vietnam",
    "VE": "Venezuela",
    "VG": "British Virgin Islands",
    "VI": "U.S. Virgin Islands",
    "VN": "Vietnam",
    "VU": "Vanuatu",
    "WF": "Wallis & Futuna",
    "WS": "Samoa",
    "XA": "Pseudo-Accents",
    "XB": "Pseudo-Bidi",
    "XK": "Kosovo",
    "YD": "Yemen",
    "YE": "Yemen",
    "YT": "Mayotte",
    "YU": "Serbia",
    "ZA": "South Africa",
    "ZM": "Zambia",
    "ZR": "Congo - Kinshasa",
    "ZW": "Zimbabwe",
    "ZZ": "Unknown Region",
}

# Codes that are US employment-reachable. The territories are here because
# calling Puerto Rico or Guam "non-US" would be wrong; they are a relocation and
# score 0 on location for that reason, not because they are a different country.
US_EQUIVALENT_CODES = frozenset({"US", "UM", "PR", "VI", "GU", "AS", "MP"})

# Names that collide with a US place. Stamped as the bare code instead. Keep in
# sync with the property test in test_tier3_gate.py, which re-derives this set.
AMBIGUOUS_NAME_CODES = frozenset({"GE", "GS"})

# Spellings the ATSes actually send that CLDR does not produce verbatim.
NAME_ALIASES = {
    "usa": "US", "u.s.": "US", "u.s": "US", "u.s.a.": "US", "u.s.a": "US",
    "united states of america": "US",
    "uk": "GB", "great britain": "GB", "england": "GB", "scotland": "GB",
    "wales": "GB", "northern ireland": "GB",
    "south korea": "KR", "north korea": "KP", "russian federation": "RU",
    "czech republic": "CZ", "viet nam": "VN", "turkey": "TR",
    "ivory coast": "CI", "cape verde": "CV", "the netherlands": "NL",
    "holland": "NL", "uae": "AE", "united arab emirates": "AE",
}

_BY_NAME = {}
for _code, _name in COUNTRY_NAMES.items():
    _BY_NAME.setdefault(_name.lower(), _code)
_BY_NAME.update(NAME_ALIASES)

# Matches "(non-US)" and "(non-US: Canada)". \b after "us" so it cannot fire on
# a location that happens to contain "(non-usual" or similar.
NON_US_TAG_RE = re.compile(r"\(non-us\b", re.I)


def normalize(value) -> str | None:
    """An ATS country field -> ISO alpha-2, or None when it is not recognised.

    Accepts a code in either case ("CA", "us") or an English name ("United
    States"). None for anything else, including the empty strings Comeet and
    Upwind return on real US postings -- unrecognised must never be read as
    non-US.
    """
    v = (value or "").strip()
    if not v:
        return None
    if len(v) == 2 and v.isalpha() and v.upper() in COUNTRY_NAMES:
        return v.upper()
    # Falls through for a two-letter value that is not a CLDR code, so the
    # alias table can answer "UK" (which ISO spells GB).
    return _BY_NAME.get(v.lower())


def display(value) -> str | None:
    """The printable country name for an ATS country field, or None.

    For the two codes whose name collides with a US place it returns the code
    instead, so a caller that splices this INTO the location string (the
    SmartRecruiters city-only fallback) can never write the word "Georgia" into
    a Tbilisi posting.
    """
    code = normalize(value)
    if code is None:
        return None
    return code if code in AMBIGUOUS_NAME_CODES else COUNTRY_NAMES[code]


def is_us(value) -> bool:
    """True only for a country field that resolves to the US or a US territory."""
    return normalize(value) in US_EQUIVALENT_CODES


def is_non_us(loc: str) -> bool:
    """True if a location string carries the stamp. Authoritative: the country
    came from a structured per-posting field, not from reading the text."""
    return bool(NON_US_TAG_RE.search(loc or ""))


def stamp(base: str, value) -> str:
    """Append the non-US country tag to an assembled location string.

    Returns `base` unchanged for a US country, an absent one, or one that does
    not resolve. Drops the country name from the tag when the base already says
    it ("Remote Bangkok, , Thailand (non-US)"), so the common SmartRecruiters
    shape does not print the country twice.
    """
    base = (base or "").strip()
    code = normalize(value)
    if code is None or code in US_EQUIVALENT_CODES or is_non_us(base):
        return base
    name = COUNTRY_NAMES.get(code)
    if not name or code in AMBIGUOUS_NAME_CODES:
        tag = f"(non-US: {code})"
    elif name.lower() in base.lower():
        tag = "(non-US)"
    else:
        tag = f"(non-US: {name})"
    return f"{base} {tag}".strip()

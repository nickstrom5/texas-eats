"""Shared helpers: name keys, casing, name matching, cuisine rules and money benchmarks.

Adapted from wi-eats/pipeline/common.py (itself from chi-eats/pipeline/build.py): Wisconsin-only words out, Colorado ones in (co-eats);
Texas words and towns added for tx-eats.
"""
import os, re, unicodedata
from rapidfuzz import fuzz

ROOT = os.path.join(os.path.dirname(__file__), "..")
DATA = os.path.join(ROOT, "data")
RAW = os.path.join(DATA, "raw")
TX = os.path.join(DATA, "tx")

STOP = {"THE", "INC", "LLC", "CO", "CORP", "RESTAURANT", "RESTAURANTS", "AND", "OF", "LTD", "CAFE", "#"}


def norm_name(s):
    # accents become their letters ("Méxican" -> MEXICAN): deleting them left fragments like "M" that matched other businesses
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = s.upper().replace("&", " AND ").replace("'S", "S").replace("’S", "S")
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = re.sub(r"\b\d{2,}\b", " ", s)  # store numbers like "#1234"
    return " ".join(w for w in s.split() if w not in STOP)


SMALL = {"of", "and", "the", "on", "at", "in", "de", "la", "el", "y", "du"}
NOT_ACRONYM = {"mr", "mrs", "ms", "st", "dr", "jr", "sr", "pl", "ct", "rd", "ln", "blvd", "pkwy", "hwy", "sq", "cr", "th", "nd", "mc",
               "cty", "hwy", "trl", "cir", "ste", "fl", "wy", "pkwy", "rr", "rt", "ne", "nw", "se", "sw"}
UNIT_TAIL = re.compile(r"(\s+(BLDG|BLD|STE|SUITE|FL|FLR|FLOOR|UNIT|RM|LOWER LEVEL|LL|APT|SPACE)\b.*$)|(\s+\d+\s*$)", re.I)


def _case(w, first, addr):
    lw = w.lower()
    if not lw:
        return w
    if first is False and lw in SMALL and not addr:
        return lw
    if lw == "bj's":
        return "BJ's"
    core = re.sub(r"[^a-z']", "", lw)
    if re.fullmatch(r"(bbq|ii|iii|iv|usa|jj|kfc|ihop|tgi|atm|llc|bp|dj|pb|vfw|amvets|ymca|uw|[a-z])", core):
        return w.upper()
    if addr and re.fullmatch(r"(ne|nw|se|sw|us|co|cr|sh)", core):
        return w.upper()
    if re.fullmatch(r"(dj|bj|jj)'s", core):
        return core[:2].upper() + core[2:] + w[len(core):]
    if not addr and core not in NOT_ACRONYM and re.fullmatch(r"[b-df-hj-np-tv-xz]{2,4}", core) and not re.search(r"(.)\1\1", core):
        return w.upper()
    if re.match(r"^mc[a-z]{3}", lw):
        return "Mc" + lw[2].upper() + lw[3:]
    if re.match(r"^o'[a-z]{2}", lw):
        return "O'" + lw[2].upper() + lw[3:]
    t = lw[:1].upper() + lw[1:]
    return re.sub(r"([-(.&])([a-z])", lambda m: m.group(1) + m.group(2).upper(), t)


def nice(s, addr=False):
    s = re.sub(r"\s+", " ", (s or "").strip())
    s = re.sub(r"(?i)\b(\w+)IES'S\b", r"\1IE'S", s)
    s = re.sub(r"(?i)'S\s+'S\b", "'S", s)
    s = re.sub(r"(?i)\bMC\s+([A-Z]{2,})", r"MC\1", s)
    if addr:   # "55 E MAIN ST STE 4" -> drop the dangling unit / stray number
        s = re.sub(r"^[^\d,]{3,},\s*(?=\d)", "", s)   # "Enter through the back, 3542 Walnut St"
        m = re.match(r"^(\d+[A-Z]?(?:\s*-\s*\d+)?\s+.+?\b(?:ST|AVE|BLVD|DR|RD|PL|CT|PKWY|TER|WAY|LN|HWY|PLZ|SQ|CIR|TRL|(?<!TO )MARKET)\b)", s, re.I)
        if m and UNIT_TAIL.search(s[m.end():]):
            road_no = re.match(r"^\s+(\d+[A-Z]?)\b", s[m.end():])
            # "8080 County Rd 12", "411 US Hwy 285": the number is the road's, not a unit
            if road_no and re.search(r"(?:\b(?:CO|COUNTY|US|STATE|SH|CR)\s+(?:RD|ROAD|HWY)|\bHWY)$", m.group(1), re.I):
                s = m.group(1) + " " + road_no.group(1)
            else:
                s = m.group(1)
    if not s:
        return s
    out = []
    words = s.split(" ")
    for i, w in enumerate(words):
        parts = re.split(r"([/@&])", w)
        cased = "".join(p if p in "/@&" else _case(p, None if i == 0 and j == 0 else False, addr) for j, p in enumerate(parts))
        if i and re.fullmatch(r"\(?co\)?[\d,]*", w.lower()) and (i == len(words) - 1 or "(" in w):   # the state code
            cased = w.upper()
        out.append(cased)
    return " ".join(out).replace("Chick-Fil-A", "Chick-fil-A")


def canon_city(c):
    """One spelling per town: St/Saint -> St., Mt/Mount -> Mount, Ft -> Fort, Spgs -> Springs, "City of X" -> X, case fixes."""
    if not isinstance(c, str) or not c.strip():
        return None
    # a state suffix needs a comma or a space before it (Colorado's "Frisco" once became "Fris"): "Frisco, TX" -> "Frisco"
    c = re.sub(r"(?:,\s*|\s+)(?:TX|Tex\.?|Texas)(?:\s+\d{5}(?:-\d{4})?)?$", "", c.strip(), flags=re.I) or c.strip()
    c = re.sub(r"^(?:City and County|City|Town)\s+of\s+", "", c, flags=re.I)
    c = nice(c) if c.isupper() or c.islower() else c
    c = re.sub(r"\b(?:Saint|St)\b\.?\s*", "St. ", c)
    c = re.sub(r"\b(?:Mount|Mt)\b\.?\s*", "Mount ", c)
    c = re.sub(r"\bFt\b\.?\s*", "Fort ", c)
    c = re.sub(r"\bSpgs?\b\.?", "Springs", c, flags=re.I)
    c = re.sub(r"\bHts\b\.?", "Heights", c)
    c = re.sub(r"\bVlg\b\.?", "Village", c, flags=re.I)
    c = re.sub(r"\s+", " ", c).strip()
    key = re.sub(r"[^a-z]", "", c.lower().replace("ñ", "n"))
    return {"ftworth": "Fort Worth", "fortworth": "Fort Worth", "ftdavis": "Fort Davis", "ftstockton": "Fort Stockton",
            "sanantonio": "San Antonio", "elpaso": "El Paso", "corpuschristi": "Corpus Christi", "grandprairie": "Grand Prairie",
            "newbraunfels": "New Braunfels", "sanmarcos": "San Marcos", "collegestation": "College Station", "roundrock": "Round Rock",
            "cedarpark": "Cedar Park", "sugarland": "Sugar Land", "missouricity": "Missouri City", "leaguecity": "League City",
            "laporte": "La Porte", "lamarque": "La Marque", "deerpark": "Deer Park", "theWoodlands": "The Woodlands",
            "thewoodlands": "The Woodlands", "woodlands": "The Woodlands", "kingwood": "Kingwood", "dfwairport": "DFW Airport",
            "dfw": "DFW Airport", "southpadreisland": "South Padre Island", "southpadre": "South Padre Island",
            "portaransas": "Port Aransas", "portarthur": "Port Arthur", "portlavaca": "Port Lavaca", "portisabel": "Port Isabel",
            "mcallen": "McAllen", "mckinney": "McKinney", "mcgregor": "McGregor", "mckinneytx": "McKinney", "mcqueeney": "McQueeney",
            "desoto": "DeSoto", "dekalb": "DeKalb", "lavernia": "La Vernia", "lagrange": "La Grange", "lajoya": "La Joya",
            "laferia": "La Feria", "lavilla": "La Villa", "lacoste": "LaCoste", "lavaca": "La Vaca", "elcampo": "El Campo",
            "delrio": "Del Rio", "delvalle": "Del Valle", "eaglepass": "Eagle Pass", "bigspring": "Big Spring",
            "wichitafalls": "Wichita Falls", "sanangelo": "San Angelo", "fredericksburg": "Fredericksburg",
            "dripping springs": "Dripping Springs", "drippingsprings": "Dripping Springs", "horseshoebay": "Horseshoe Bay",
            "marblefalls": "Marble Falls", "ftbliss": "Fort Bliss", "forthood": "Fort Cavazos", "ftcavazos": "Fort Cavazos",
            "ftsamhouston": "Fort Sam Houston", "jbsasamhouston": "Fort Sam Houston", "nrichlandhills": "North Richland Hills",
            "northrichlandhills": "North Richland Hills", "richlandhills": "Richland Hills", "universalcity": "Universal City",
            "lakejackson": "Lake Jackson", "texascity": "Texas City", "bigbendnationalpark": "Big Bend National Park",
            "terlingua": "Terlingua", "southlake": "Southlake", "flowermound": "Flower Mound", "thecolony": "The Colony",
            "farmersbranch": "Farmers Branch", "grandsaline": "Grand Saline", "cedarhill": "Cedar Hill", "highlandvillage": "Highland Village",
            "unionvale": "Union Vale", "hurst": "Hurst", "bedford": "Bedford", "euless": "Euless", "kellerTX": "Keller"}.get(key, c)


def town_key(c):
    k = c.lower().replace(".", " ")
    k = re.sub(r"^(e|n|s|w)\s+", lambda m: {"e": "east ", "n": "north ", "s": "south ", "w": "west "}[m.group(1)], k)
    k = re.sub(r"\bmt\b", "mount", k); k = re.sub(r"\bhts\b", "heights", k); k = re.sub(r"\bft\b", "fort", k)
    return re.sub(r"[^a-z]", "", k)


# words that don't identify a business on their own: a name match needs a shared word outside this list
GENERIC = set("""PIZZA PIZZERIA PHO TACO TACOS TAQUERIA GRILL GRILLE KITCHEN EXPRESS HOUSE COFFEE BAR PUB TAVERN FOOD FOODS STORE SHOP MARKET
DELI BAKERY CHICKEN FISH BBQ SUSHI THAI CHINESE MEXICAN INDIAN ITALIAN GYROS BURGER BURGERS WINGS DONUTS DONUT BEEF TEA JUICE
NORTH SOUTH EAST WEST PARK SQUARE STATION UNION TOWN VILLAGE STREET AVE AVENUE CENTER PLAZA LAKE LAKES RIVER BAY
NEW OLD BEST GOLDEN LITTLE BIG KING STAR ORIGINAL FAMOUS FRESH HOT GRAND LA EL LOS LAS DE DEL ON THE Y AT OF LOUNGE SNACK SNACKS
NOODLE NOODLES ASIAN SHRIMP PATIO CLUB SUPPER INN LODGE SALOON RESORT BREWING BREWERY COMPANY BREW HALL FROZEN CHEESE
FRY COLORADO BAKE CAFETERIA CORNER SPOT STOP PLACE ROOM SPORTS FAMILY STEAKHOUSE STEAK DINER CREAMERY ICE CREAM
HUT WOK MEAL FUSION BUFFET CUISINE EATS EATERY MOUNTAIN MOUNTAINS ROCKY MILE HIGH PEAK PEAKS ALPINE SUMMIT CANYON CREEK MESA RANCH
GREEN CHILE CHILI BURRITO BURRITOS TAPROOM TAPHOUSE DEN BISTRO TRADING POST WESTERN FRONT RANGE CO SKI
TEXAS TEX MEX TEXMEX LONE TX HILL COUNTRY BRISKET KOLACHE KOLACHES ICEHOUSE CANTINA COWBOY GULF COAST BAYOU SMOKEHOUSE SMOKE PIT
CRAWFISH BOUDIN TAQUERIAS BARBACOA FAJITA FAJITAS ENCHILADA ENCHILADAS TAMALE TAMALES POLLO VALLEY BORDER""".split())


def _stems(s):
    # one- and two-letter fragments ("A", "C", "MR", "LE") never count as a distinctive word
    return {w if w in GENERIC else (w[:-1] if len(w) > 3 and w.endswith("S") else w) for w in s.split() if len(w) >= 3 or w.isdigit()} - GENERIC


def name_sim(a, b):
    ours, theirs = set(a.split()), set(b.split())
    distinct = (_stems(a) - GENERIC) & (_stems(b) - GENERIC)
    joined = a.replace(" ", "") == b.replace(" ", "") or fuzz.ratio(a.replace(" ", ""), b.replace(" ", "")) >= 92
    if joined:
        return 96
    if not distinct and fuzz.ratio(a, b) < 95:   # nothing but generic words in common: not the same business
        return 60
    s_set = fuzz.token_set_ratio(a, b)
    # token_set_ratio is 100 whenever one name's words are a subset of the other's: cap it unless the overlap is a real share of both
    if len(ours & theirs) < 0.5 * min(len(ours), len(theirs)) + 0.5 or len(ours & theirs) < 0.4 * max(len(ours), len(theirs)):
        s_set = min(s_set, 72)
    return max(s_set, fuzz.ratio(a, b), fuzz.token_sort_ratio(a, b))


FOODCAT = re.compile(r"\b(restaurant|cafe|coffee|bakery|pizza|bar|pub|diner|deli|taco|ice cream|donut|dessert|sandwich|food court|caterer|tea house|bistro|brewpub|brewery|juice|grill|takeout|buffet|bagel|chicken|seafood|steak|hot dog|tavern|lounge|gastropub|snack|yogurt|creperie|patisserie|chocolate|confectionery|bubble tea|night club|beer|wine|bbq|barbecue|pie|pastry|popcorn|tamale|churro|takeaway|tortilleria|fish & chips|cheesesteak)\b", re.I)
NOTFOOD = re.compile(r"^(?:Tower|Museum|Stadium|Convention|Hotel|Performing|Theater|Hospital|University|Corporate|Observation|Tourist|Airport|Casino|Gas station|Grocery|Supermarket|Convenience|Liquor store|Event|Banquet|Park|Arena)\b")

# Name keywords -> cuisine. Whole words only, so HOSPITAL isn't "PITA", BREWING isn't "WING", BOWLING isn't "BOWL".
# Order matters: specific before general.
_W = lambda words: re.compile(r"\b(?:" + words + r")\b")
CUISINE_RULES = [
    ("Hot Dogs & Sausages", _W(r"HOT ?DOGS?|DOGS|WIENERS?|BRATS?|BRATWURST|SAUSAGES?|ITALIAN BEEF|RED HOTS?|BIKER JIMS")),
    ("Pizza", _W(r"PIZZA|PIZZAS|PIZZERIA|PIZZERIAS|DOMINOS|PAPA JOHNS|LITTLE CAESARS?|TOPPERS|ROCKY ROCOCO|GLASS NICKEL|PIZZA RANCH|BEAU JOS|WOODYS PIZZA|ANTHONYS PIZZA")),
    ("Korean", _W(r"KOREAN?|KOREA|KIMCHI|BIBIMBAP|SEOUL|GOGI|BULGOGI|KBBQ|CUPBOP")),
    ("Thai", _W(r"THAI|SIAM|BANGKOK|ISAAN|ISAN")),
    ("Vietnamese", _W(r"PHO|VIETNAMESE|VIETNAM|SAIGON|BANH MI|BANH|HANOI")),
    ("Coffee & Café", _W(r"COFFEE|ESPRESSO|STARBUCKS|DUNKIN|CAFFE|TEA|TEAS|TEAHOUSE|BOBA|DAZBOG|ZIGGIS|HUCKLEBERRY ROASTERS|LATTE|ROASTERS?|ROASTING|KAFFE|KAFFEE")),
    ("Bakery & Sweets", _W(r"BAKERY|BAKERIES|BAKESHOP|BAKE SHOP|BAKEHOUSE|PASTRY|PASTRIES|PATISSERIE|DONUTS?|DOUGHNUTS?|PANADERIA|CAKES?|CUPCAKES?|COOKIES?|DESSERTS?|ICE CREAM|GELATO|GELATERIA|PALETERIA|PALETAS|YOGURT|FROYO|CREPES?|CREPERIE|SWEETS|CHOCOLATE|CHOCOLATIER|CINNABON|BAGELS?|CREAMERY|CHURROS?|PIES|KRINGLE|KOLACHES?|KOLACHE|DO NUTS|SHIPLEYS?|CONFECTIONS?|MICHOACANA|DAIRY QUEEN|BASKIN")),
    ("Mexican", _W(r"TEX MEX|TEXMEX|FAJITAS?|ENCHILADAS?|BARBACOA|MENUDO|TAQUERIA|TAQUERIAS|TACOS?|MEXICAN[AO]?|MEXICO|BURRITOS?|BIRRIA|BIRRIERIA|CARNITAS|TAMALES?|TORTAS?|ELOTES?|MARISCOS|CHIPOTLE|QDOBA|AZTECA|JALISCO|MICHOACAN|GUADALAJARA|OAXACA|GUERRERO|PUEBLA|CANTINA|TORTILLERIA|ANTOJITOS?|QUESADILLAS?|NACHOS?|HUARACHES?|FONDA|EL TORO|TAQUERIA|ILLEGAL PETES|SANTIAGOS|GREEN CHILE|SMOTHERED|SLOPPERS?")),
    ("Latin & Caribbean", _W(r"CUBAN[AO]?|CUBA|PUERTO RICAN|BORINQUEN|CARIBBEAN|JAMAICAN?|JERK|HAITIAN?|PERUVIAN|PERU|COLOMBIAN[AO]?|COLOMBIA|SALVADOREN[AO]|PUPUSAS?|PUPUSERIA|ARGENTIN[AE]|ARGENTINIAN|VENEZUELAN?|AREPAS?|BRAZILIAN?|EMPANADAS?|DOMINICAN|GUATEMALTEC[AO]|HONDUREN[AO]|ECUADORIAN|LATIN[AO]?|CEVICHE")),
    ("Japanese & Sushi", _W(r"SUSHI|RAMEN|JAPANESE|JAPAN|IZAKAYA|TERIYAKI|HIBACHI|OMAKASE|TOKYO|BENTO|UDON|YAKITORI|KATSU|SAKE|TEMPURA|SASHIMI|TEPPANYAKI|KYOTO|OSAKA|BENIHANA")),
    ("German & European", _W(r"PELMENI|PIEROGI|PIEROGIES|BELGIAN|DUTCH|MELTING POT|FONDUE|SCHNITZEL|BIERGARTEN|BIERHALLE|RATSKELLER|RATHSKELLER|SERBIAN|POLISH|GERMAN|BAVARIAN")),
    ("Chinese", _W(r"CHINA|CHINESE|EGG ROLLS?|WOK|DUMPLINGS?|DIM SUM|PANDA EXPRESS|HUNAN|SZECHUAN|SICHUAN|MANDARIN|CANTONESE|KUNG PAO|HONG KONG|BEIJING|SHANGHAI|HOT ?POT|CHOP SUEY|BAO|LO MEIN|WONTON|PEKING|YUNNAN")),
    ("South Asian", _W(r"INDIA|INDIAN|TANDOOR|TANDOORI|CURRY|CURRIES|MASALA|BIRYANI|NEPAL|NEPALI|NEPALESE|HIMALAYAN?|PAKISTANI?|BOMBAY|MUMBAI|DELHI|PUNJAB|PUNJABI|KATHMANDU|MOMOS?|CHAAT|SAMOSAS?|BENGALI|SRI LANKAN?|DOSA|TIKKA")),
    ("Mediterranean & Middle Eastern", _W(r"GREEK|GYROS?|MEDITERRANEAN|MEDITERANNEAN|FALAFEL|SHAWARMA|MIDDLE EASTERN|LEBANESE|HALAL|KABOBS?|KEBABS?|KABABS?|PERSIAN|TURKISH|ISRAELI|HUMMUS|PITA|PITAS|ZAATAR|SYRIAN|AFGHAN|ARABIC|ARABIAN|ATHENS|OLYMPIA|PARTHENON|AEGEAN|NAF NAF|MEZZE|ASSYRIAN|YEMENI|ZAROB")),
    ("African", _W(r"AFRICAN?|AFRICA|ETHIOPIAN?|NIGERIAN?|ERITREAN?|GHANAIAN|SENEGALESE|SOMALI|MOROCCAN|EGYPTIAN|KENYAN|CAMEROONIAN|JOLLOF|SUYA")),
    ("Italian", _W(r"ITALIAN[AO]?|ITALIA|TRATTORIA|OSTERIA|PASTA|RISTORANTE|VINO|NONNA|CUCINA|ENOTECA|SPAGHETTI|NAPOLI|NAPOLETANA|SICILIAN|TUSCANY|TUSCAN|FORNO|MAGGIANOS|OLIVE GARDEN|BARTOLOTTA")),
    ("Burgers", _W(r"BURGERS?|HAMBURGERS?|CHEESEBURGERS?|BUTTERBURGERS?|MCDONALDS|MC DONALDS|WENDYS|WHITE CASTLE|FIVE GUYS|SHAKE SHACK|CULVERS|SMASHBURGER|PATTY|PATTIES|STEAK N SHAKE|SONIC|ARBYS|CHECKERS|JACK IN THE BOX|WHATABURGER|HARDEES|A AND W|GOOD TIMES|BAD DADDYS|CRAFTY CRAWLER")),
    ("Seafood", _W(r"SEAFOOD|FISH|FISHERIES|FISHERY|SHRIMP|OYSTERS?|CRABS?|CRAB|LOBSTER|CATFISH|CAJUN|BOIL|CRAWFISH|POKE|TROUT|LONG JOHN SILVERS|CAPTAIN DS")),
    ("Chicken & Wings", _W(r"CHICKEN|WINGS|POPEYES|KFC|CHURCHS|RAISING CANES?|CHICK FIL A|BROASTED|WINGSTOP|NASHVILLE HOT|KRISPY KRUNCHY")),
    ("BBQ", _W(r"BBQ|BAR B Q|BAR BQ|BAR B QUE|BAR BE CUE|BAR B CUE|BARBECUE|BARBEQUE|RIBS|SMOKEHOUSE|SMOKED|BRISKET|FAMOUS DAVES|RUDYS|DICKEYS|SMOKE PIT|PIT ROOM")),
    ("Sandwiches & Deli", _W(r"SANDWICH|SANDWICHES|DELI|DELICATESSEN|SUBWAY|JIMMY JOHNS|POTBELLY|JERSEY MIKES|FIREHOUSE SUBS|SUBS|HOAGIES?|PANERA|CORNER BAKERY|CHEESE ?STEAKS?|PHILLY|CAPRIOTTIS|SNARFS|CHEBA HUT|SUB SHOP")),
    ("Steakhouse", _W(r"STEAK|STEAKS|STEAKHOUSE|STEAK HOUSE|CHOPHOUSE|CHOP HOUSE|RUTHS CHRIS|CAPITAL GRILLE|MORTONS|TEXAS ROADHOUSE|LONGHORN|OUTBACK|PRIME RIB|BUCKHORN")),
    ("Soul & Southern", _W(r"SOUL|SOUTHERN|CREOLE|GUMBO|BOUDIN|CHICKEN FRIED|BISCUITS?|GRITS|CHICKEN WAFFLES")),
    ("Healthy & Vegan", _W(r"VEGAN|VEGETARIAN|SALADS?|JUICE|JUICERY|SMOOTHIES?|SWEETGREEN|PLANT BASED|ACAI|HEALTHY|ORGANIC|JAMBA|NOODLES AND COMPANY|MAD GREENS|MODERN MARKET|GARBANZO")),
    ("Breakfast & Diner", _W(r"BREAKFAST|PANCAKES?|DINER|BRUNCH|EGGS?|IHOP|DENNYS|PERKINS|YOLK|OMELETTES?|OMELETS?|SUNRISE|MORNING|WAFFLES?|GRIDDLE|SKILLETS?|SNOOZE|LUCILES|VILLAGE INN|BAGEL")),
    ("German & European", _W(r"POLISH|POLSKA|UKRAINIAN|GERMAN|BAVARIAN|SERBIAN|BOSNIAN|CROATIAN|RUSSIAN|FRENCH|BRASSERIE|IRISH|BRITISH|SWEDISH|NORWEGIAN|NORSKE|DANISH|SPANISH|TAPAS|PORTUGUESE|EUROPEAN|LITHUANIAN|CZECH|HUNGARIAN|ROMANIAN|GEORGIAN|PIEROGI|PIEROGIES|HAUS|BIERGARTEN|BEER GARDEN|BIERHALLE|RATHSKELLER|STUBE|SCHNITZEL|SWISS|SLOVENIAN|FONDUE")),
    ("Bar & Pub", _W(r"PUB|TAVERN|BAR|SALOON|LOUNGE|TAP|TAPS|TAPROOM|TAPHOUSE|BREWING|BREWERY|BREWPUB|BEER|ALE HOUSE|GASTROPUB|COCKTAILS?|WINE|WINERY|DISTILLERY|DISTILLING|INN|PADDY|BARS")),
]
GCAT = [(c, re.compile(p)) for c, p in [
    ("Pizza", r"Pizza"), ("Coffee & Café", r"Coffee|Cafe|Espresso|Tea house|Bubble tea"),
    ("Bakery & Sweets", r"Bakery|Donut|Dessert|Ice cream|Pastry|Cake|Frozen yogurt|Chocolate|Bagel|Pie shop|Candy"),
    ("Mexican", r"Mexican|Taco|Burrito|Tex-Mex|Taqueria"), ("Latin & Caribbean", r"Latin|Caribbean|Cuban|Puerto Rican|Jamaican|Peruvian|Colombian|Salvadoran|Brazilian|Venezuelan|Argentin|Haitian"),
    ("Japanese & Sushi", r"Japanese|Sushi|Ramen"), ("Chinese", r"Chinese|Cantonese|Dim sum|Szechuan|Dumpling|Hot pot"),
    ("Korean", r"Korean"), ("Thai", r"Thai"), ("Vietnamese", r"Vietnamese|Pho"), ("South Asian", r"Indian|Pakistani|Nepal|Bangladeshi|Sri Lankan"),
    ("Mediterranean & Middle Eastern", r"Mediterranean|Middle Eastern|Greek|Lebanese|Falafel|Halal|Turkish|Persian|Israeli|Afghan|Shawarma"),
    ("African", r"African|Ethiopian|Nigerian|Moroccan|Eritrean|Somali"), ("Italian", r"Italian"),
    ("Hot Dogs & Sausages", r"Hot dog|Italian beef|Bratwurst"), ("Burgers", r"Hamburger|Burger"), ("Seafood", r"Seafood|Fish|Oyster|Poke|Cajun"),
    ("Chicken & Wings", r"Chicken"), ("BBQ", r"Barbecue"), ("Steakhouse", r"Steak"),
    ("Soul & Southern", r"Soul food|Southern"), ("Sandwiches & Deli", r"Sandwich|Deli|Cheesesteak"),
    ("Healthy & Vegan", r"Vegan|Vegetarian|Health food|Salad|Juice"), ("Breakfast & Diner", r"Breakfast|Brunch|Diner|Pancake"),
    ("German & European", r"French|German|Polish|Ukrainian|Spanish|Tapas|Irish|European|Eastern European|Serbian|Russian|Bistro|Scandinavian|Swiss|Belgian|Dutch|Fondue"),
    ("Bar & Pub", r"Bar\b|Pub|Brewpub|Brewery|Tavern|Gastropub|Wine bar|Cocktail|Beer"),
    # a primary "American" category is an answer too, so a later "Bar" tag doesn't turn a family restaurant into a pub
    ("American & Other", r"American restaurant|Eclectic restaurant|Fine dining restaurant|Family restaurant|Southwestern"),
]]


def cuisine(name_key, gcats, raw=""):
    for c, pat in CUISINE_RULES:
        if pat.search(name_key or ""):
            return c
    cats = [x for x in (gcats or "").split("|") if x]
    for cat in cats:
        for c, pat in GCAT:
            if pat.search(cat):
                return c
    if re.search(r"\bCAF[EÉ]\b", (raw or "").upper()) and not cats:
        return "Coffee & Café"
    return "American & Other"


# Typical food-cost % by cuisine (industry rule-of-thumb ranges, midpoint)
FOOD_COST = {"Pizza": 26, "Coffee & Café": 24, "Bakery & Sweets": 25, "Mexican": 28, "Latin & Caribbean": 30,
             "Japanese & Sushi": 34, "Chinese": 30, "Korean": 32, "Thai": 30, "Vietnamese": 30, "South Asian": 28,
             "Mediterranean & Middle Eastern": 30, "African": 30, "Italian": 29, "Hot Dogs & Sausages": 31, "Burgers": 31,
             "Chicken & Wings": 33, "Seafood": 36, "BBQ": 34, "Steakhouse": 38, "Soul & Southern": 32,
             "Sandwiches & Deli": 30, "Healthy & Vegan": 32, "Breakfast & Diner": 27, "German & European": 30, "Bar & Pub": 27,
             "American & Other": 30}
# Pre-tax net margin benchmarks by segment
MARGIN = {1: 0.075, 2: 0.05, 3: 0.055, 4: 0.045}
MARGIN_CUISINE = {"Bar & Pub": 0.10, "Steakhouse": 0.09, "Pizza": 0.07, "Coffee & Café": 0.08}
SPEND = {1: 13, 2: 28, 3: 62, 4: 165}   # typical per-person spend by price tier

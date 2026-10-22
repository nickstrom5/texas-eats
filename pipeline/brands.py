"""Known chain brands in Texas: regex on normalized name -> brand label.

Adapted from wi-eats/pipeline/brands.py; Wisconsin-only brands dropped, Colorado and Mountain West chains added (co-eats),
Texas chains added for tx-eats.
"""
import re

BRANDS = [
    ("Dunkin'", r"^DUNKIN"), ("Subway", r"^SUBWAY"), ("McDonald's", r"^MC ?DONALDS"), ("Starbucks", r"^STARBUCK"),
    ("Jimmy John's", r"^JIMMY JOHN"), ("Burger King", r"^BURGER KING"), ("Taco Bell", r"^TACO BELL"),
    ("Potbelly", r"^POTBELLY"), ("Wingstop", r"^WING ?STOP"), ("Chipotle", r"^CHIPOTLE"), ("Popeyes", r"^POPEYE"),
    ("Wendy's", r"^WENDYS"), ("Panda Express", r"^PANDA EXPRESS"), ("White Castle", r"^WHITE CASTLE"),
    ("Chick-fil-A", r"^CHICK FIL"), ("Domino's", r"^DOMINO"), ("Jersey Mike's", r"^JERSEY MIKE"),
    ("Panera Bread", r"^PANERA"), ("Jet's Pizza", r"^JETS PIZZA"), ("Little Caesars", r"^LITTLE CAESAR"),
    ("Papa John's", r"^PAPA JOHN"), ("KFC", r"^KFC|^KENTUCKY FRIED"), ("Tropical Smoothie Cafe", r"^TROPICAL SMOOTHIE"),
    ("Buffalo Wild Wings", r"^BUFFALO WILD"), ("Five Guys", r"^FIVE GUYS"), ("Raising Cane's", r"^RAISING CANE"),
    ("Portillo's", r"^PORTILLO"), ("Auntie Anne's", r"^AUNTIE ANNE"), ("Qdoba", r"^QDOBA"),
    ("Noodles & Company", r"^NOODLES (?:AND )?CO(?:MPANY)?\b"), ("Smoothie King", r"^SMOOTHIE KING"), ("Firehouse Subs", r"^FIREHOUSE SUB"),
    ("IHOP", r"^IHOP"), ("Denny's", r"^DENNYS"), ("Sonic", r"^SONIC DRIVE|^SONIC$"), ("Insomnia Cookies", r"^INSOMNIA COOKIE"),
    ("Crumbl", r"^CRUMBL"), ("Dairy Queen", r"^DAIRY QUEEN|^DQ GRILL|^DQ$"), ("Baskin-Robbins", r"^BASKIN"), ("Krispy Kreme", r"^KRISPY KREME"),
    ("Chuck E. Cheese", r"^CHUCK E CHEESE"), ("Rosati's", r"^ROSATI"), ("Nothing Bundt Cakes", r"^NOTHING BUNDT"),
    ("Hooters", r"^HOOTERS"), ("Cheesecake Factory", r"^CHEESECAKE FACTORY"), ("P.F. Chang's", r"^P ?F CHANG"), ("Maggiano's", r"^MAGGIANO"),
    ("Ruth's Chris", r"^RUTHS CHRIS"), ("Morton's", r"^MORTONS THE STEAK|^MORTONS STEAK"), ("Steak 'n Shake", r"^STEAK N SHAKE"),
    ("Applebee's", r"^APPLEBEE"), ("Chili's", r"^CHILIS"), ("Olive Garden", r"^OLIVE GARDEN"), ("Red Lobster", r"^RED LOBSTER"),
    ("Jamba", r"^JAMBA"), ("Cinnabon", r"^CINNABON"), ("Pizza Hut", r"^PIZZA HUT"), ("Arby's", r"^ARBYS"),
    ("Checkers", r"^CHECKERS DRIVE|^CHECKERS AND RALLY|^CHECKERS$"), ("MOD Pizza", r"^MOD PIZZA"), ("Tim Hortons", r"^TIM HORTON"),
    ("Peet's Coffee", r"^PEETS"), ("Colectivo", r"^COLECTIVO"), ("Cava", r"^CAVA$|^CAVA (?:MEDITERRANEAN|GRILL)"), ("Blaze Pizza", r"^BLAZE PIZZA"),
    # national chains common in Colorado, and Colorado's own
    ("Culver's", r"^CULVER"), ("Taco John's", r"^TACO JOHN"), ("Caribou Coffee", r"^CARIBOU COFFEE|^CARIBOU$"),
    ("Scooter's Coffee", r"^SCOOTERS COFFEE"), ("Dutch Bros", r"^DUTCH BRO"), ("7 Brew", r"^7 BREW"), ("The Human Bean", r"^(?:THE )?HUMAN BEAN"),
    ("Black Rock Coffee", r"^BLACK ROCK COFFEE"), ("Ziggi's Coffee", r"^ZIGGIS"), ("Dazbog Coffee", r"^DAZBOG"),
    ("Texas Roadhouse", r"^TEXAS ROADHOUSE"), ("Famous Dave's", r"^FAMOUS DAVE"), ("Red Robin", r"^RED ROBIN"),
    ("Freddy's", r"^FREDDYS FROZEN|^FREDDYS STEAKBURGER"), ("Papa Murphy's", r"^PAPA MURPH"), ("Marco's Pizza", r"^MARCOS PIZZA"),
    ("Cracker Barrel", r"^CRACKER BARREL"), ("Outback Steakhouse", r"^OUTBACK STEAK"), ("LongHorn Steakhouse", r"^LONGHORN STEAK"),
    ("Cold Stone Creamery", r"^COLD STONE"), ("Golden Corral", r"^GOLDEN CORRAL"),
    ("Old Chicago", r"^OLD CHICAGO$|^OLD CHICAGO (?:PASTA|PIZZA|TAPROOM)"), ("Rock Bottom", r"^ROCK BOTTOM"),
    ("Einstein Bros. Bagels", r"^EINSTEIN BRO"), ("Quiznos", r"^QUIZNO"), ("Fazoli's", r"^FAZOLI"), ("Dickey's Barbecue Pit", r"^DICKEYS"),
    ("HuHot Mongolian Grill", r"^HUHOT"), ("Blimpie", r"^BLIMPIE"), ("Dave's Hot Chicken", r"^DAVES HOT CHICKEN"), ("Sbarro", r"^SBARRO"),
    ("Great Harvest", r"^GREAT HARVEST"), ("Teriyaki Madness", r"^TERIYAKI MADNESS"), ("First Watch", r"^FIRST WATCH"),
    ("TGI Fridays", r"^TGI FRIDAY"), ("Mooyah", r"^MOOYAH"), ("Charleys Cheesesteaks", r"^CHARLEYS"), ("Smashburger", r"^SMASHBURGER"),
    ("Hunt Brothers Pizza", r"^HUNT BROTHERS"), ("Hot Stuff Pizza", r"^HOT STUFF"), ("Krispy Krunchy Chicken", r"^KRISPY KRUNCHY"),
    ("Cheba Hut", r"^CHEBA HUT"), ("MrBeast Burger", r"^MR ?BEAST"), ("It's Just Wings", r"^ITS JUST WINGS"), ("7-Eleven", r"^7 ELEVEN"),
    ("Casey's", r"^CASEYS"), ("Pizza Ranch", r"^PIZZA RANCH"), ("Hardee's", r"^HARDEES"), ("Carl's Jr.", r"^CARLS JR"),
    ("Jack in the Box", r"^JACK IN THE BOX"), ("Del Taco", r"^DEL TACO"), ("Whataburger", r"^WHATABURGER"), ("In-N-Out Burger", r"^IN N OUT"),
    ("Café Rio", r"^CAFE RIO"), ("Costa Vida", r"^COSTA VIDA"), ("Cafe Yumm!", r"^CAFE YUMM"), ("Waffle House", r"^WAFFLE HOUSE"),
    ("Perkins", r"^PERKINS (?:RESTAURANT|BAKERY|AMERICAN|FAMILY)|^PERKINS$"), ("Bob Evans", r"^BOB EVANS"), ("Black Bear Diner", r"^BLACK BEAR DINER"),
    ("Native Grill & Wings", r"^NATIVE GRILL"), ("BJ's Restaurant", r"^BJS RESTAURANT|^BJS BREWHOUSE"), ("Twin Peaks", r"^TWIN PEAKS"),
    ("Kneaders", r"^KNEADERS"), ("Swig", r"^SWIG$"), ("Crave Cookies", r"^CRAVE COOKIE"), ("Paris Baguette", r"^PARIS BAGUETTE"),
    ("Sweetgreen", r"^SWEETGREEN"), ("Torchy's Tacos", r"^TORCHYS"), ("Velvet Taco", r"^VELVET TACO"), ("Fuzzy's Taco Shop", r"^FUZZYS TACO"),
    ("Slim Chickens", r"^SLIM CHICKENS"), ("Zaxby's", r"^ZAXBY"), ("Bojangles", r"^BOJANGLES"), ("Church's Chicken", r"^CHURCHS (?:TEXAS )?CHICKEN"),
    ("Hooters", r"^HOOTERS"), ("Dairy Queen", r"^DAIRY QUEEN|^DQ GRILL|^DQ$"),
    # Colorado-born or Colorado-heavy chains
    ("Illegal Pete's", r"^ILLEGAL PETE"), ("Snarf's", r"^SNARFS"), ("Good Times", r"^GOOD TIMES (?:BURGERS|DRIVE)|^GOOD TIMES$"),
    ("Village Inn", r"^VILLAGE INN"), ("Garbanzo", r"^GARBANZO"), ("Modern Market", r"^MODERN MARKET"), ("Tokyo Joe's", r"^TOKYO JOE"),
    ("Smiling Moose", r"^SMILING MOOSE"), ("Snooze", r"^SNOOZE"), ("Lucile's", r"^LUCILES"), ("Bad Daddy's Burger Bar", r"^BAD DADDYS"),
    ("Mad Greens", r"^MAD GREENS"), ("Larkburger", r"^LARKBURGER"), ("Spicy Pickle", r"^SPICY PICKLE"), ("Sweet Cow", r"^SWEET COW"),
    ("Beau Jo's", r"^BEAU JO"), ("Anthony's Pizza & Pasta", r"^ANTHONYS PIZZA"), ("Blackjack Pizza", r"^BLACKJACK PIZZA"),
    ("Abo's Pizza", r"^ABOS PIZZA|^ABOS$"), ("Woody's Wings", r"^WOODYS WINGS"), ("Fat Shack", r"^FAT SHACK"), ("Wing Shack", r"^WING SHACK"),
    ("Santiago's", r"^SANTIAGOS"), ("Las Delicias", r"^LAS DELICIAS"), ("Tacos y Salsas", r"^TACOS Y SALSAS"), ("Birdcall", r"^BIRDCALL"),
    ("Brothers BBQ", r"^BROTHERS BBQ|^BROTHERS BAR B Q"), ("Moe's Original BBQ", r"^MOES ORIGINAL"), ("Famous Philly's", r"^FAMOUS PHILLYS"),
    ("Biker Jim's", r"^BIKER JIMS"), ("Kaladi Coffee", r"^KALADI"), ("Pablo's Coffee", r"^PABLOS COFFEE"), ("Novo Coffee", r"^NOVO COFFEE"),
    ("Huckleberry Roasters", r"^HUCKLEBERRY ROASTERS"), ("Corvus Coffee", r"^CORVUS"), ("Little Man Ice Cream", r"^LITTLE MAN ICE CREAM"),
    ("Rocky Mountain Chocolate Factory", r"^ROCKY MOUNTAIN CHOCOLATE"), ("Sam's No. 3", r"^SAMS NO 3"), ("Racca's", r"^RACCAS"),
    ("Odell Brewing", r"^ODELL BREWING"), ("New Belgium", r"^NEW BELGIUM"), ("Breckenridge Brewery", r"^BRECKENRIDGE BREWERY"),
    ("Tequila's", r"^TEQUILAS (?:FAMILY )?MEXICAN"), ("El Tapatio", r"^EL TAPATIO"), ("Señor Sol", r"^SENOR SOL"),
    ("Juan's Flying Burrito", r"^JUANS FLYING"), ("Rosie's Diner", r"^ROSIES DINER"), ("Bonchon", r"^BONCHON"), ("Chuy's", r"^CHUYS"),
    ("Kum & Go", r"^KUM (?:AND )?GO"), ("Maverik", r"^MAVERIK"), ("Loaf 'N Jug", r"^LOAF N JUG"), ("Love's", r"^LOVES TRAVEL"),
    # Texas-born or Texas-heavy chains (names only; no logos)
    ("Buc-ee's", r"^BUC ?EES"), ("Shipley Do-Nuts", r"^SHIPLEY"), ("Kolache Factory", r"^KOLACHE FACTORY"), ("Rudy's", r"^RUDYS (?:COUNTRY STORE|BAR B Q|BBQ)"),
    ("Pappadeaux", r"^PAPPADEAUX"), ("Pappasito's", r"^PAPPASITO"), ("Pappas Bros. Steakhouse", r"^PAPPAS BRO"), ("Pappas Bar-B-Q", r"^PAPPAS BAR"),
    ("Taco Cabana", r"^TACO CABANA"), ("Taco Palenque", r"^TACO PALENQUE"), ("Bill Miller Bar-B-Q", r"^BILL MILLER"), ("Pluckers", r"^PLUCKERS"),
    ("Freebirds", r"^FREEBIRDS"), ("Babe's Chicken Dinner House", r"^BABES CHICKEN"), ("Lupe Tortilla", r"^LUPE TORTILLA"),
    ("Mi Cocina", r"^MI COCINA"), ("El Chico", r"^EL CHICO"), ("Pollo Regio", r"^POLLO REGIO"), ("Pollo Tropical", r"^POLLO TROPICAL"),
    ("Layne's Chicken Fingers", r"^LAYNES"), ("Golden Chick", r"^GOLDEN CHICK"), ("Bush's Chicken", r"^BUSHS CHICKEN"), ("Mooyah", r"^MOOYAH"),
    ("Black Walnut Cafe", r"^BLACK WALNUT"), ("Snooze", r"^SNOOZE"), ("Kerbey Lane", r"^KERBEY LANE"), ("P. Terry's", r"^P TERRYS"),
    ("Schlotzsky's", r"^SCHLOTZSKY"), ("Jason's Deli", r"^JASONS DELI"), ("Corner Bakery", r"^CORNER BAKERY"), ("Saltgrass Steak House", r"^SALTGRASS"),
    ("Pok-e-Jo's", r"^POKE JOS"), ("Cotton Patch Cafe", r"^COTTON PATCH"), ("Mama's Pizza", r"^MAMAS PIZZA"), ("Rosa's Café", r"^ROSAS CAFE"),
    ("Tumbleweed TexMex", r"^TUMBLEWEED"), ("Grimaldi's", r"^GRIMALDI"), ("Mi Tienda", r"^MI TIENDA"), ("Stripes", r"^STRIPES"),
    ("Valero", r"^VALERO"), ("Shell", r"^SHELL$"), ("H-E-B", r"^H E B\b|^HEB\b"), ("Kroger", r"^KROGER"), ("Tom Thumb", r"^TOM THUMB"),
    ("Cane Rosso", r"^CANE ROSSO"), ("Dodie's Cajun Diner", r"^DODIES"), ("Rodeo Goat", r"^RODEO GOAT"), ("Hopdoddy", r"^HOPDODDY"),
    ("Tacodeli", r"^TACODELI"), ("Tacos Tu Madre", r"^TACOS TU MADRE"), ("Taqueria Arandas", r"^TAQUERIA ARANDAS"), ("James Coney Island", r"^JAMES CONEY"),
]
_C = [(b, re.compile(p)) for b, p in BRANDS]

# distinctive brands also recognized mid-name ("HALE FAMILY MCDONALDS", "SAII BABA DUNKIN")
_ANYWHERE = [(b, re.compile(p)) for b, p in [("McDonald's", r"\bMC ?DONALDS\b"), ("Dunkin'", r"\bDUNKIN\b"), ("Starbucks", r"\bSTARBUCKS\b"),
             ("Wingstop", r"\bWING ?STOP\b"), ("Culver's", r"\bCULVERS\b"), ("Popeyes", r"\bPOPEYES\b"), ("Chipotle", r"\bCHIPOTLE\b"),
             ("Jimmy John's", r"\bJIMMY JOHNS\b"), ("Taco Bell", r"\bTACO BELL\b"), ("Illegal Pete's", r"\bILLEGAL PETES\b")]]


def brand_of(nkey, *more):
    """Brand from the display name, else from Overture's brand label."""
    keys = [k for k in [nkey] + [m for m in more if isinstance(m, str)] if isinstance(k, str)]
    for k in keys:
        for part in [k or ""] + [p.strip() for p in (k or "").split("/")]:
            for b, p in _C:
                if p.search(part):
                    return b
    for k in keys:
        for b, p in _ANYWHERE:
            if p.search(k or ""):
                return b
    return None

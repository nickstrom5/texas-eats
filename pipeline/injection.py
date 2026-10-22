"""Hijacked-page detector for restaurant websites, used by check_websites.py.

Hacked small-business sites carry planted links: casino, betting, adult, pharma and link-farm spam, often hidden off-screen,
in zero-size or display:none blocks, or in <noscript>. Club Oasis (Sparta) had a block at left:-5466px linking a Polish casino
(2026-10-12). scan() returns every reason a page looks hijacked, with evidence; parked() spots parked, expired and default pages.

Built from the cross-state QA session's detector (2026-10-12, tested on Club Oasis, 9 planted variants, 7 look-alikes and 16
real pages), with two fixes to the first injected(): only named real casinos are exempt (a bare "casino" in a host exempted
milkywaycasino.pl itself), and there is no bare negative-offset rule (margin-top:-138px is layout, not hiding); hidden blocks
are judged by what they link to (HIDE_STYLE below needs a property boundary and position:absolute or 4+ digits).
"""
import re
import urllib.parse


def _netloc(u):
    """The host of a link, or "" for a malformed one ("http://[broken", seen on a Texas page): it must not stop the checker."""
    try:
        return urllib.parse.urlparse(u).netloc
    except ValueError:
        return ""

SPAM = re.compile(r"slot ?gacor|situs (?:slot|judi|togel)|slot online|\bslot ?88\b|\btogel\b|judi (?:online|bola|slot|qq|poker)|perjudian|"
                  r"bandar ?(?:slot|qq|togel)|\bmaxwin\b|\brtp slot|\bsbobet\b|\bbahis|casino siteleri|\b1win\b|watch porn|free porn|"
                  r"porn videos?|\bpornhub\b|\bxvideos\b|\bxnxx\b|escort service|adult dating|sex cam|camgirl", re.I)
BLOBS = re.compile(r"[A-Za-z0-9+/=_-]{100,}")   # base64 images and tokens: random letters spell anything
BETTING = re.compile(r"online casino|casino online|deposit bonus|sportsbook|\bbaccarat\b|bet365|no deposit", re.I)
BETTING_PROSE = re.compile(r"online casino|casino online|deposit bonus|sportsbook|bet365|no deposit", re.I)   # no Baccarat crystal
GAMBLING_HOST = re.compile(r"casino|kasyno|kasino|kazino|(?:^|[.-])slots?(?:[.-]|$)|slot(?:88|gacor|online)|togel|gacor|bahis|1xbet|"
                           r"mostbet|melbet|parimatch|22bet|bet365|betway|(?:^|[.-])bet(?:[.-]|$)|bukmacher", re.I)
FOREIGN_CASINO = re.compile(r"\bkasyn|казино|bukmacher|zakłady bukmacherskie|darmow\w* spin|apuestas deportivas|casino en l[ií]nea|"
                            r"spielautomat|\bgokken\b|free spins", re.I)
FOREIGN_CASINO_LINK = re.compile(FOREIGN_CASINO.pattern + r"|scommesse", re.I)   # only in links away
LINK = re.compile(r"""<a\b[^>]*\bhref=["'](https?://[^"']+)["'][^>]*>(.*?)</a>""", re.I | re.S)
HEAD = re.compile(r"<title[^>]*>(.*?)</title>|<meta[^>]+name=.description.[^>]+content=\"([^\"]*)", re.S)
CASINO_PLACE = re.compile(r"casino|gaming|potawatomi|ho-?chunk|oneida|menominee|mohican|north ?star|lake of the torches|"
                          r"st\.? ?croix|bad river|legendary waters|isle vista|grindstone", re.I)
PARKED = re.compile(r"domain (?:is|may be) for sale|buy this domain|this domain is parked|parked free|sedoparking|hugedomains|"
                    r"afternic|domain has expired|this domain name has expired|account (?:has been )?suspended|website coming soon|"
                    r"site (?:is )?coming soon|future home of|launching soon|godaddy\.com/domainsearch|(?<![\w.-])dan\.com", re.I)


def regdom(host):
    parts = host.lower().removeprefix("www.").split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "net") and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])



# Real casinos outside Wisconsin that restaurant pages link to (tribal and commercial): their own hosts are exempt, like
# CASINO_PLACE's Wisconsin list. Matched against the linked host.
CASINO_HOSTS_OK = re.compile(r"mohegansun|foxwoods|seminolehardrock|hardrock|seminole|miccosukee|coeurdalene|cdacasino|kootenai|"
                             r"tulalip|snoqualmie|muckleshoot|emeraldqueen|angelofthewinds|clearwatercasino|sevenfeathers|"
                             r"pechanga|morongo|sycuan|viejas|barona|harrahs|caesars|mgm|ameristar|isleofcapri|blackhawk|"
                             r"monarchcasino|thelodgecasino|turningstone|resortsworld|empirecitycasino|delawarenorth|"
                             r"oxfordcasino|hollywoodcasino|pennentertainment|wynn|venetian|sands|seneca|delmonte|"
                             r"rivercree|ute|skyute|sleepingute|ignacio|potawatomi|hochunk|oneida|menominee|mohican|northstar|"
                             # Wisconsin's tribal casinos as they appear in hosts (Northwoods Inn links Mole Lake Casino)
                             r"molelake|sokaogon|ho-chunk|northernlights|stcroix|lakeofthetorches|badriver|legendarywaters|"
                             r"grindstone|isle-?vista|menomineecasino|northstarcasino|oneidacasino|carter", re.I)
REAL_CASINO_PLACE = re.compile(CASINO_PLACE.pattern.replace("casino|gaming|", ""), re.I)
# Adult and pharma link spam: hosts, link text and page text. Kept to words with no ordinary restaurant meaning.
ADULT_HOST = re.compile(r"porn|xvideos|xnxx|xhamster|redtube|youporn|onlyfans|chaturbate|stripchat|bongacams|livejasmin|camsoda|"
                        r"brazzers|(?:^|[.-])sex(?:[.-]|$)|sexcam|sexchat|sexdating|hookup|adultfriend|escorts?(?:[.-]|$)|xxx(?!root)", re.I)
PHARMA_WORDS = (r"viagra|cialis|levitra|kamagra|tadalafil|sildenafil|vardenafil|propecia|finasteride|tramadol|xanax|alprazolam|valium|"
                r"diazepam|ambien(?!t)|zolpidem|oxycodone|oxycontin|hydrocodone|modafinil|phentermine|clomid|accutane|isotretinoin")
PHARMA_HOST = re.compile(r"(?:^|[.-]|buy|cheap|generic|order|get|best|discount)(?:" + PHARMA_WORDS + r")|online-?pharmacy|"
                         r"pharmacy-?online|canadian-?pharmacy|rx-?pills|buy-?pills|cheap-?(?:pills|meds)|apotheke|apteka|"
                         r"farmacia|roidshop|steroids?(?:shop|store|online|forsale)|(?:buy|cheap)-?steroids?", re.I)
PHARMA_TEXT = re.compile(r"\b(?:" + PHARMA_WORDS + r")\b|online pharmacy|without (?:a )?prescription|cheap pills|erectile dysfunction|"
                         r"anabolic steroids?|steroids? (?:shop|store|drugs|for sale|online)|buy steroids?",
                         re.I)
ADULT_TEXT = re.compile(r"\bporn\w*|\bxxx (?:videos?|movies?|sex)|\bsex (?:videos?|chat|dating|tube|cams?)|\bescorts? (?:in|service)|"
                        r"\bhookups? (?:site|app)|\bnude (?:girls|cams?|videos?)|\bonlyfans\b|\bcam ?girls?\b", re.I)
# Other link-farm vocabulary seen in hacked small-business sites (only counted inside hidden blocks or in links away).
FARM_TEXT = re.compile(r"payday loans?|title loans?|essay (?:writing|writer|service)|write my (?:essay|paper)|buy (?:essays?|followers)|"
                       r"replica (?:watches|handbags|rolex)|cheap (?:jerseys|ugg|nfl)|crypto ?casino|bitcoin casino|"
                       r"betting (?:sites?|tips|odds)|slot (?:machines?|sites?|demo)|mail.order brides?|\bjudi\b|\bslot\b|\bpoker online\b",
                       re.I)
# Inline styles that hide a block: display:none, visibility:hidden, zero/one-pixel size with overflow hidden, font-size 0,
# opacity 0, clip to nothing. Matched on the opening tag's style attribute.
UI_HIDE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden|(?<![\w-])(?:max-)?height\s*:\s*0(?:px)?\s*(?:;|$|!)", re.I)
# off-page hiding: off-screen offsets (not margin-top/-left, which layouts use), zero or one pixel boxes, font-size 0,
# opacity 0, clipped to nothing
HIDE_STYLE = re.compile(r"(?<![\w-])width\s*:\s*[01](?:px)?\s*(?:;|$|!)|(?<![\w-])height\s*:\s*1px\s*(?:;|$|!)|"
                        r"font-size\s*:\s*0(?:px|em|rem|pt)?\s*(?:;|$|!)|(?<![\w-])opacity\s*:\s*0(?:\.0+)?\s*(?:;|$|!)|"
                        r"clip\s*:\s*rect\(\s*0|(?<![\w-])(?:left|right|top|text-indent)\s*:\s*-\d{4,}(?:px|em|rem)|"
                        r"(?<![\w-])(?:left|right|top)\s*:\s*-\d{3,}(?:px|em|rem)[^\"']*position\s*:\s*absolute|"
                        r"position\s*:\s*absolute[^\"']*(?<![\w-])(?:left|right|top)\s*:\s*-\d{3,}(?:px|em|rem)", re.I)
HIDDEN_OPEN = re.compile(r"""<(div|span|p|section|ul|ol|li|font|aside|marquee|small)\b([^>]*\bstyle\s*=\s*(["'])(.*?)\3[^>]*)>""",
                         re.I | re.S)
HIDDEN_ATTR = re.compile(r"""<(div|span|p|section|ul|ol|aside)\b([^>]*\s(?:hidden|aria-hidden=["']true["'])[^>]*)>""", re.I | re.S)
NOSCRIPT = re.compile(r"<noscript\b[^>]*>(.*?)</noscript>", re.I | re.S)
TAG = re.compile(r"<[^>]+>")
# Hosts a legitimate restaurant page links to from hidden menus, modals and noscript fallbacks: social, ordering, booking,
# maps, apps, payments, site builders, analytics and fonts. A hidden block that links only to these is not a link farm.
BENIGN_HOST = re.compile(
    r"(?:^|\.)(?:facebook|fb|instagram|twitter|x|tiktok|youtube|youtu|pinterest|linkedin|yelp|tripadvisor|google|goo|googleapis|"
    r"gstatic|googletagmanager|apple|doordash|grubhub|ubereats|uber|postmates|seamless|slicelife|toasttab|toast|square|squareup|"
    r"squarespace|wix|wixsite|weebly|godaddy|wordpress|wp|shopify|clover|chownow|menufy|beyondmenu|opentable|resy|exploretock|tock|"
    r"sevenrooms|yelpreservations|bentobox|getbento|popmenu|spothopperapp|spothopper|untappd|eventbrite|mailchimp|list-manage|"
    r"constantcontact|paypal|venmo|giftup|giftfly|squareup|vagaro|linktr|linktree|w3|schema|cloudflare|jquery|bootstrapcdn|"
    r"fontawesome|typekit|adobe|microsoft|bing|mapquest|openstreetmap|waze|indeed|ziprecruiter|workstream|harri|toasttab|"
    r"order(?:online|food)?|ezcater|catering|olo|dine|menu|zmenu|allmenus|menupages|thanx|punchh|paytronix|spoton|heartland|"
    r"revelsystems|lightspeed|tripadvisor|foursquare|snapchat|threads|vimeo|soundcloud|spotify|addtoany|sharethis|addthis|"
    r"browsehappy|enable-javascript|whatismybrowser|mozilla|getfirefox|chrome|outlook|gmail|zendesk|hubspot|intuit|"
    r"recaptcha|hcaptcha|cookiebot|onetrust|termly|iubenda|accessibe|userway|audioeye|w3c)\.[a-z.]+$", re.I)


def _away(own):
    def away(h):
        return regdom(_netloc(h)) not in own
    return away


def _snip(s, n=300):
    return re.sub(r"\s+", " ", s).strip()[:n]


def _close_block(body, start, tag, limit=20000):
    """Body of the element whose opening tag ends at `start`, honouring nesting of the same tag (bounded)."""
    depth, i = 1, start
    pat = re.compile(r"<(/?)%s\b[^>]*>" % tag, re.I)
    for m in pat.finditer(body, start, min(len(body), start + limit)):
        if m.group(1):
            depth -= 1
            if depth == 0:
                return body[start:m.start()]
        elif not m.group(0).endswith("/>"):
            depth += 1
    return body[start:start + limit]


def hidden_blocks(body):
    """(kind, inner html) for every inline-hidden element, aria/hidden-attribute element and <noscript> block."""
    out = []
    for m in HIDDEN_OPEN.finditer(body):
        style = m.group(4)
        if HIDE_STYLE.search(style):
            out.append(("style:" + _snip(style, 80), _close_block(body, m.end(), m.group(1))))
        elif UI_HIDE.search(style):
            out.append(("ui:" + _snip(style, 80), _close_block(body, m.end(), m.group(1))))
    for m in NOSCRIPT.finditer(body):
        out.append(("noscript", m.group(1)))
    return out


def scan(body, host, final, name=""):
    """Every reason this page looks hijacked, each with its evidence: [(rule, evidence)]. Empty list = clean.
    Includes the original injected() verdict as rule 'wi:injected' so the two can be compared."""
    reasons = []
    text = BLOBS.sub(" ", body).lower()
    own = {regdom(host), regdom(_netloc(final))}
    away = _away(own)
    # the place itself is a casino: its name says so, or its own host is a named real casino. Not "casino" in the final host:
    # a taken-over restaurant domain that redirects to a casino would earn the exemption.
    casino_place = bool(CASINO_PLACE.search(name or "") or CASINO_HOSTS_OK.search(host) or REAL_CASINO_PLACE.search(host))
    head = " ".join(a or b for a, b in HEAD.findall(text[:60_000]))
    # --- the original Wisconsin rules (check() + injected())
    m = SPAM.search(text) or SPAM.search(final)
    if m:
        reasons.append(("wi:spam-text", _ctx(text, m) if SPAM.search(text) else final))
    if not casino_place:
        mb = BETTING.search(head)
        if mb or len(BETTING_PROSE.findall(text)) >= 2:
            mm = mb and BETTING.search(text) or BETTING_PROSE.search(text)
            reasons.append(("wi:betting-words", _ctx(text, mm) if mm else head[:200]))
        if injected(body, text, host, final):
            reasons.append(("wi:injected", _why_injected(body, text, away)))
    # --- extensions
    links = LINK.findall(body)
    for h, t in links:
        if not away(h):
            continue
        hh = _netloc(h).lower()
        tt = TAG.sub(" ", t)
        if ADULT_HOST.search(hh) or ADULT_TEXT.search(tt):
            reasons.append(("ext:adult-link", f"{h} :: {_snip(tt, 120)}"))
        if PHARMA_HOST.search(hh) or PHARMA_TEXT.search(tt):
            reasons.append(("ext:pharma-link", f"{h} :: {_snip(tt, 120)}"))
        if (HOST_4D.search(hh) or CJK_GAMBLING.search(tt) or INDO_GAMING.search(tt)) and not casino_place:
            reasons.append(("ext:lottery-link", f"{h} :: {_snip(tt, 120)}"))
        if FARM_TEXT.search(tt) and not BENIGN_HOST.search(hh):
            reasons.append(("ext:farm-link-text", f"{h} :: {_snip(tt, 120)}"))
        # the original exempts any host matching CASINO_PLACE, which includes the bare word "casino": milkywaycasino.pl
        # passed the link rule (Club Oasis was caught only by its Polish text and the off-screen block). Here only named
        # real casinos are exempt.
        if not casino_place and not CASINO_HOSTS_OK.search(hh) and not REAL_CASINO_PLACE.search(hh) and \
                (GAMBLING_HOST.search(hh) or BETTING.search(tt) or FOREIGN_CASINO_LINK.search(tt)):
            reasons.append(("ext:gambling-link", f"{h} :: {_snip(tt, 120)}"))
    vis = re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", text, flags=re.S)
    vis = TAG.sub(" ", vis)
    mf = FOREIGN_EXT.search(vis)
    if mf and not casino_place:   # Thai, Vietnamese, Korean, Japanese, Portuguese, Turkish, Arabic, Russian, Indonesian gambling words
        reasons.append(("ext:foreign-gambling-text", _ctx(vis, mf)))
    if len(JP_SPAM.findall(vis)) >= 2:
        reasons.append(("ext:jp-keyword-spam", _ctx(vis, JP_SPAM.search(vis))))
    # a title or description that sells gambling, pills or porn (stricter than v2: not bare "slots" or "judi", which are
    # "darts & slots" at Angry Bob's and the name Judi's Place)
    if not casino_place and (SPAM.search(head) or BETTING_PROSE.search(head) or FOREIGN_CASINO.search(head) or FOREIGN_EXT.search(head)
                             or CJK_GAMBLING.search(head) or PHARMA_TEXT.search(head) or JP_SPAM.search(head)):
        reasons.append(("ext:spam-title", _snip(head, 200)))
    for am in A_STYLE.finditer(body):   # the link itself hidden off-page
        sm = STYLE_ATTR.search(am.group(1))
        h_ = am.group(2)
        if sm and away(h_) and OFFSCREEN_POS.search(sm.group(2)) and not BENIGN_HOST.search(_netloc(h_).lower()):
            reasons.append(("ext:hidden-anchor", f"[{_snip(sm.group(2), 60)}] {h_}"))
            break
    for mo, payload in _decoded_payloads(body):   # eval(atob/unescape/fromCharCode) that loads or sends you elsewhere
        hosts = [x for x in (_netloc(u_).lower() for u_ in re.findall(r"""https?://[^\s'"<>)]+""", payload))
                 if x and away("https://" + x)]
        if hosts and re.search(r"createElement|\.src\s*=|location|window\.open|<iframe|<script", payload, re.I):
            reasons.append(("ext:obfuscated-script", f"decoded: {_snip(payload, 200)}"))
            break
    mc = CJK_GAMBLING.search(head) or CJK_GAMBLING.search(vis)
    if mc and not casino_place:
        reasons.append(("ext:cjk-gambling", _ctx(vis, mc) if CJK_GAMBLING.search(vis) else head[:200]))
    mi = INDO_GAMING.search(head) or INDO_GAMING.search(vis)
    if mi and not casino_place:
        reasons.append(("ext:indonesian-gaming", _ctx(vis, mi) if INDO_GAMING.search(vis) else head[:200]))
    m4 = LOTTERY_4D.search(head) or LOTTERY_4D.search(vis)
    if m4 and not casino_place:
        reasons.append(("ext:lottery-4d", _ctx(vis, m4) if LOTTERY_4D.search(vis) else head[:200]))
    mp = PHARMA_TEXT.search(vis)
    if mp and len(PHARMA_TEXT.findall(vis)) >= 2:
        reasons.append(("ext:pharma-text", _ctx(vis, mp)))
    ma = ADULT_TEXT.search(vis)
    if ma and len(ADULT_TEXT.findall(vis)) >= 2:
        reasons.append(("ext:adult-text", _ctx(vis, ma)))
    for kind, block in hidden_blocks(body):
        bl = LINK.findall(block)
        aw = [(h, TAG.sub(" ", t)) for h, t in bl if away(h)]
        if not aw:
            continue
        suspicious = [(h, t) for h, t in aw if not BENIGN_HOST.search(_netloc(h).lower())]
        spammy = [(h, t) for h, t in aw if GAMBLING_HOST.search(_netloc(h)) or ADULT_HOST.search(
            _netloc(h)) or PHARMA_HOST.search(_netloc(h)) or BETTING.search(t)
            or FOREIGN_CASINO_LINK.search(t) or ADULT_TEXT.search(t) or PHARMA_TEXT.search(t) or FARM_TEXT.search(t)]
        doms = {regdom(_netloc(h)) for h, _ in suspicious}
        # display:none / visibility:hidden hide menus, dropdowns and modals with sister-restaurant links: only spam counts
        if spammy or (len(doms) >= 3 and not kind.startswith("ui:")):
            ex = "; ".join(f"{h} :: {_snip(t, 60)}" for h, t in (spammy or suspicious)[:5])
            reasons.append(("ext:hidden-" + ("noscript" if kind == "noscript" else "block"), f"[{kind}] {ex}"))
        elif suspicious and not kind.startswith("ui:") and kind != "noscript" and OFFSCREEN_POS.search(kind):
            reasons.append(("ext:offpage-link", f"[{kind}] " + "; ".join(h for h, _ in suspicious[:3])))
    # one rule per kind is enough for triage; keep the first evidence of each
    seen, out = set(), []
    for r, e in reasons:
        if r not in seen:
            seen.add(r)
            out.append((r, e))
    return out


def _ctx(s, m, w=150):
    a, b = max(0, m.start() - w), min(len(s), m.end() + w)
    return _snip(s[a:b], 2 * w + 60)


def _why_injected(body, text, away):
    for h, t in LINK.findall(body):
        hh = _netloc(h).lower()
        if away(h) and not CASINO_HOSTS_OK.search(hh) and not REAL_CASINO_PLACE.search(hh) and \
                (GAMBLING_HOST.search(hh) or BETTING.search(t) or FOREIGN_CASINO_LINK.search(t)):
            return f"link {h} :: {_snip(TAG.sub(' ', t), 120)}"
    m = FOREIGN_CASINO.search(text)
    if m:
        return "foreign casino text: " + _ctx(text, m)
    return "?"


# Lottery and gaming vocabulary the English rules can't see: Chinese lottery sites (Rupp's Supperclub's old domain became a
# "lucky 168 airship" lottery page, 2026-10-12) and Indonesian 4D lottery names (harum4d, in California). Only gambling words:
# no ordinary Chinese menu word (幸运 "lucky", 北京 "Beijing") is on the list.
CJK_GAMBLING = re.compile(r"体彩|彩票|时时彩|六合彩|飞艇|北京赛车|幸运赛车|开奖|博彩|赌场|赌博|百家乐|老虎机|棋牌|真人娱乐|"
                          r"娛樂城|博弈|賭場|彩票網|六合彩")
# 4D lottery phrases in text; a "<name>4d" host only in links (in text it matched CSS colours like #ffffff4d and file names)
LOTTERY_4D = re.compile(r"\b(?:situs|link) (?:toto|4d)\b|\btoto (?:macau|4d|sgp|hk)\b", re.I)
HOST_4D = re.compile(r"(?:^|[.-])[a-z]{3,}4d\d*(?:[.-]|$)", re.I)
# Indonesian slot-site vocabulary (Takarajima Sushi's title: "situs link spaceman slot ... gampang menang")
INDO_GAMING = re.compile(r"gampang menang|pragmatic play|\bsitus link\b|spaceman slot|slot spaceman|\bslot gacor\b|\bgacor\b.{0,40}\bslot|"
                         r"\bmaxwin\b|\blink alternatif\b|\bdaftar (?:slot|akun)\b", re.I)


# ---- more languages, hidden anchors, off-page links and decoded loaders (from the cross-state QA scanner v2, 2026-10-12)
FOREIGN_EXT = re.compile(r"สล็อต|บาคาร่า|แทงบอล|เว็บพนัน|nhà cái|cá cược|nổ hũ|카지노|토토사이트|바카라|博彩|娱乐城|百家乐|赌场|"
                         r"老虎机|オンラインカジノ|カジノ|cassino online|apostas esportivas|casa de apostas|tragamonedas|"
                         r"deneme bonusu|canlı casino|كازينو|ставки на спорт|букмекер|онлайн казино|игровые автоматы|"
                         r"situs judi|slot gacor|link alternatif|体彩|彩票|飞艇|时时彩|六合彩|北京赛车|开奖记录|网投|\bkemenangan\b", re.I)
JP_SPAM = re.compile(r"スーパーコピー|激安|送料無料|通販|楽天市場|新品未使用|ブランドコピー|偽物|格安|最安値|販売店|人気商品")
OBFUSCATED = re.compile(r"eval\s*\(\s*(?:String\.fromCharCode|atob|unescape|decodeURIComponent|function\s*\(\s*p\s*,\s*a\s*,\s*c\s*,\s*k)",
                        re.I)
A_STYLE = re.compile(r"""<a\b([^>]*\bhref=["'](https?://[^"']+)["'][^>]*)>(.*?)</a>""", re.I | re.S)
STYLE_ATTR = re.compile(r"""\bstyle\s*=\s*(["'])(.*?)\1""", re.I | re.S)
OFFSCREEN_POS = re.compile(r"(?<![\w-])(?:left|right|top)\s*:\s*-\d{4,}(?:px|em|rem)|"
                           r"(?<![\w-])(?:left|right|top)\s*:\s*-\d{3,}(?:px|em|rem)[^\"']*position\s*:\s*absolute|"
                           r"position\s*:\s*absolute[^\"']*(?<![\w-])(?:left|right|top)\s*:\s*-\d{3,}(?:px|em|rem)", re.I)
OBF_CALL = re.compile(r"""eval\s*\(\s*(atob|unescape|decodeURIComponent)\s*\(\s*(['"])(.{8,20000}?)\2\s*\)|"""
                      r"""eval\s*\(\s*String\.fromCharCode\s*\(([\d\s,]{8,40000})\)""", re.I | re.S)


def _decoded_payloads(body):
    import base64
    for m in OBF_CALL.finditer(body):
        try:
            if m.group(4):
                s = "".join(chr(int(x)) for x in m.group(4).replace(" ", "").split(",") if x.strip())
            elif m.group(1).lower() == "atob":
                b = m.group(3); b += "=" * (-len(b) % 4)
                s = base64.b64decode(b).decode("utf-8", "replace")
            else:
                s = urllib.parse.unquote(m.group(3))
        except Exception:
            continue
        yield m, s



PARKING_HOSTS = re.compile(r"(?:^|\.)(?:sedo|sedoparking|parkingcrew|bodis|above|hugedomains|afternic|dan|godaddy|domainmarket|"
                           r"undeveloped|buydomains|namebright|uniregistry|epik|domainnameshop|parklogic|perfectdomain|"
                           r"brandbucket|squadhelp|atom|efty|sav|spaceship|porkbun|namecheap|dynadot|domain-for-sale|"
                           r"domainlore|domainagents|smartname|fabulous|trafficz|voodoo|skenzo|searchhounds|"
                           r"expired|suspendedpage)\.[a-z.]+$", re.I)
PARKED_EXTRA = re.compile(r"this domain (?:name )?(?:is|may be) (?:for sale|available)|is for sale!?|make an offer|"
                          r"inquire about this domain|related searches|domain parking|parked domain|this page is parked|"
                          r"the domain .{0,60} (?:has expired|is not configured)|renew (?:now|your domain)|"
                          r"site not found|domain not found|no such app|there isn't a github pages site here|"
                          r"this site can.t be reached|default web site page|apache2 (?:ubuntu|debian) default page|"
                          r"welcome to nginx|apache.{0,80}\bit works!|^\s*it works!|index of /|website is (?:under construction|suspended)|"
                          r"this account has been suspended|account suspended|bandwidth limit exceeded|"
                          r"site is currently unavailable|wix\.com.{0,40}(?:error|connect your domain)|"
                          r"looks like this domain isn.t connected|this site is not published|"
                          r"squarespace.{0,40}(?:expired|website expired)|website expired|this website has expired|"
                          r"get your own website|domain .{0,40} is parked free", re.I)


def parked(body, final):
    """(rule, evidence) when the page is parked, for sale, expired, a default server page or a builder's 'not found'."""
    text = BLOBS.sub(" ", body).lower()
    vis = TAG.sub(" ", re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", text, flags=re.S))
    vis = re.sub(r"\s+", " ", vis)
    fh = _netloc(final).lower()
    if PARKING_HOSTS.search(fh):
        return ("parking-host", final)
    # a host's placeholder instead of a site: cPanel sends a meta refresh to its default or suspended page (Mihm's, 2026-10-12)
    m = re.search(r"/cgi-sys/(?:defaultwebpage|suspendedpage)\.cgi", text)
    if m:
        return ("hosting-placeholder", _ctx(text, m))
    m = PARKED.search(text[:60_000])
    if m:
        return ("wi:parked", _ctx(text, m))
    m = PARKED_EXTRA.search(vis[:20_000])
    if m and len(vis) < 8000:   # a full restaurant site that mentions "make an offer" is not parked
        return ("parked", _ctx(vis, m))
    return None


def injected(body, text, host, final):
    """True for a page linking away to a gambling host, or with casino words in such a link or in another language.
    Only named real casinos are exempt (REAL_CASINO_PLACE, CASINO_HOSTS_OK below); hidden blocks are scan()'s job."""
    own = {regdom(host), regdom(_netloc(final))}
    for h, t in LINK.findall(body):
        hh = _netloc(h).lower()
        if regdom(hh) in own or CASINO_HOSTS_OK.search(hh) or REAL_CASINO_PLACE.search(hh):
            continue
        if GAMBLING_HOST.search(hh) or BETTING.search(t) or FOREIGN_CASINO.search(t):
            return True
    return bool(FOREIGN_CASINO.search(text))



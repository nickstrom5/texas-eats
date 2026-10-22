import Foundation

/// Search that matches the start of words, the way the web leaderboard does:
/// "frankl" finds Franklin Barbecue, "n lamar" finds N Lamar Blvd, "ft worth" = "Fort Worth", a town in the query narrows to that town,
/// and "barbecue", "taqueria" or "kolaches" mean those Texas guides (or a place named that way). A dish ("brisket", "breakfast
/// tacos") is an ordinary word: it finds the hand-checked places that serve it, not a whole guide.
struct Search {
    static let typeSynonyms = ["avenue": "ave", "av": "ave", "street": "st", "boulevard": "blvd", "road": "rd", "drive": "dr", "place": "pl",
                               "court": "ct", "parkway": "pkwy", "highway": "hwy", "lane": "ln", "trail": "trl", "circle": "cir", "terrace": "ter"]
    /// directions and Texas road names: "north lamar" finds "N Lamar Blvd", "interstate 35" finds "I-35"
    static let synonyms: [String: String] = typeSynonyms.merging(["north": "n", "south": "s", "east": "e", "west": "w", "northwest": "nw", "northeast": "ne",
                                                                  "southwest": "sw", "southeast": "se", "saint": "st", "mount": "mt", "fort": "ft",
                                                                  "interstate": "i", "ih": "i", "freeway": "fwy", "expressway": "expy"]) { a, _ in a }
    static let abbreviations = Set(synonyms.values)
    static let typeAbbreviations = Set(typeSynonyms.values)
    static let tagPhrases: [(String, PlaceTags)] = [("barbecue", .bbq), ("barbeque", .bbq), ("bbq", .bbq), ("tex mex", .texMex),
                                                   ("texmex", .texMex), ("taquerias", .taqueria), ("taqueria", .taqueria), ("kolaches", .kolache),
                                                   ("kolache", .kolache), ("chicken fried steak", .chickenFried), ("chicken fried steaks", .chickenFried),
                                                   ("chicken-fried steak", .chickenFried)]

    /// Lowercase, no accents or apostrophes, "&" as "and" ("B&B" stays "bb"), everything else a single space.
    /// One pass over the characters instead of three regular expressions: it runs four times per place at launch
    /// (testNormalizeMatchesTheRegexVersion keeps it equal to the regex version on every bundled name and address).
    static func normalize(_ s: String) -> String {
        var t = s.folding(options: [.diacriticInsensitive, .caseInsensitive], locale: .init(identifier: "en_US")).lowercased()
        if t.contains("&") {
            t = t.replacingOccurrences(of: #"\b([a-z0-9])\s*&\s*([a-z0-9])\b"#, with: "$1$2", options: .regularExpression)
            t = t.replacingOccurrences(of: "&", with: " and ")
        }
        var out = String.UnicodeScalarView()
        var gap = false
        for c in t.unicodeScalars {
            if c == "'" || c == "\u{2019}" || c == "`" { continue }
            switch c.properties.generalCategory {
            case .uppercaseLetter, .lowercaseLetter, .titlecaseLetter, .modifierLetter, .otherLetter,
                 .decimalNumber, .letterNumber, .otherNumber:
                if gap && !out.isEmpty { out.append(" ") }
                gap = false
                out.append(c)
            default:
                gap = true
            }
        }
        return String(out)
    }

    /// Addresses (only) get their street words abbreviated so "north avenue" finds "N Ave".
    static func normalizeAddress(_ s: String) -> String {
        normalize(s).split(separator: " ").map { synonyms[String($0)] ?? String($0) }.joined(separator: " ")
    }

    struct Query {
        var tokens: [[String]] = []     // each token: needles, any of which may match
        var town: String?
        var townPhrase: String?
        var tag: PlaceTags?
        var tagPhrase: String?
        /// worked out once per query, not once per place: " stone crab" for "stone crabs", " st petersburg" for the town
        var tagStem: String?
        var townNeedle: String?
        var isEmpty: Bool { tokens.isEmpty && town == nil && tag == nil }
    }

    /// `towns` maps a normalized town name ("st petersburg", "port st lucie") to its display name.
    static func parse(_ text: String, towns: [String: String]) -> Query {
        var q = Query()
        var raw = normalize(text).split(separator: " ").map(String.init)
        guard !raw.isEmpty else { return q }
        var mapped = raw.map { synonyms[$0] ?? $0 }
        func find(_ phrase: String) -> Range<Int>? {
            let p = phrase.split(separator: " ").map(String.init)
            guard p.count <= mapped.count else { return nil }
            for i in 0...(mapped.count - p.count) where Array(mapped[i..<i + p.count]) == p { return i..<i + p.count }
            return nil
        }
        func cut(_ r: Range<Int>) -> String {
            let words = raw[r].joined(separator: " ")
            raw.removeSubrange(r); mapped.removeSubrange(r)
            return words
        }
        for (phrase, tag) in tagPhrases {
            if let r = find(normalize(phrase)) { q.tag = tag; q.tagPhrase = cut(r); break }
        }
        if let phrase = q.tagPhrase {
            let stem = normalize(phrase).replacingOccurrences(of: #"s$"#, with: "", options: .regularExpression)
            q.tagStem = stem.isEmpty ? nil : " " + stem
        }
        // the longest town named in the query wins, unless a street type follows it ("orlando dr" is a street)
        for key in towns.keys.sorted(by: { $0.count > $1.count }) {
            if let r = find(key), !(r.upperBound < mapped.count && typeAbbreviations.contains(mapped[r.upperBound])) {
                q.town = towns[key]; q.townPhrase = cut(r); q.townNeedle = " " + normalize(q.townPhrase ?? ""); break
            }
        }
        let stop: Set<String> = ["the", "and", "of", "a", "in", "near", "me"]   // "stone crab near me" isn't Mexican places
        var idx = Array(raw.indices)
        // stop words stay only when they're all there is ("the"); next to a guide or a town ("oyster bar near me") they go
        if q.tag != nil || q.town != nil || idx.contains(where: { !stop.contains(mapped[$0]) }) { idx = idx.filter { !stop.contains(mapped[$0]) } }
        for (n, i) in idx.enumerated() {
            let token = raw[i], isLast = n == idx.count - 1
            if let abbr = synonyms[token] { q.tokens.append([" \(abbr) ", " \(token)"]); continue }
            let whole = (abbreviations.contains(token) && (!isLast || token.count > 1)) || (token.count <= 2 && !isLast)
            var needles = [" " + token + (whole ? " " : "")]
            if isLast && token.count >= 3 {
                for (word, abbr) in typeSynonyms where word != token && word.hasPrefix(token) { needles.append(" \(abbr) ") }
            }
            q.tokens.append(needles)
        }
        // "brady st": a finished street type sticks to the word before it
        if q.tokens.count >= 2, let last = idx.last, typeAbbreviations.contains(mapped[last]) {
            let prev = idx[idx.count - 2]
            q.tokens.removeLast(2)
            q.tokens.append([" \(mapped[prev]) \(mapped[last]) ", " \(raw[prev]) \(raw[last])"])
        }
        return q
    }

    static func matches(_ p: Place, _ q: Query) -> Bool {
        if let tag = q.tag, !p.tags.contains(tag) {
            guard let stem = q.tagStem, p.nameText.contains(stem) else { return false }
        }
        if let town = q.town, p.city != town {
            guard let needle = q.townNeedle, p.nameText.contains(needle) else { return false }
        }
        for needles in q.tokens where !needles.contains(where: { p.searchText.contains($0) }) { return false }
        return true
    }

    /// Name matches first ("golden" puts Golden Mill ahead of every place in Golden).
    static func nameMatches(_ p: Place, _ q: Query) -> Bool {
        !q.tokens.isEmpty && q.tokens.allSatisfy { needles in needles.contains { p.nameText.contains($0) } }
    }
}

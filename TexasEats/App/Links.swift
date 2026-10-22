import Foundation

/// The app's web pages and support address, in one place.
/// The site is GitHub Pages at the project address until texas.eatsranked.com resolves (Nick adds a Cloudflare CNAME
/// texas -> nickstrom5.github.io, DNS only; then scripts/make-site.py sets CUSTOM_DOMAIN). GitHub forwards these github.io
/// links to the custom domain after the switch, so a shipped build keeps working; point them at the new domain in the next update.
enum Links {
    static let site = URL(string: "https://nickstrom5.github.io/texas-eats/")!
    static let privacy = URL(string: "https://nickstrom5.github.io/texas-eats/privacy.html")!
    static let terms = URL(string: "https://nickstrom5.github.io/texas-eats/terms.html")!
    /// TABC's public license search (a page that opens and works; a place shows its license number to look up)
    static let tabcSearch = URL(string: "https://www.tabc.texas.gov/public-information/tabc-public-inquiry/")!
    /// the open dataset behind TABC licenses and the Comptroller's reported alcohol sales
    static let tabcData = URL(string: "https://data.texas.gov/d/7hf9-qc9f")!
    static let mixbevData = URL(string: "https://data.texas.gov/d/naix-2893")!
    static let supportEmail = "nick@eatsranked.com"

    static var correctionEmail: URL {
        URL(string: "mailto:\(supportEmail)?subject=Texas%20Eats%20correction")!
    }
}

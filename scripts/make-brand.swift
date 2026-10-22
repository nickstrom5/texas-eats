// Texas Eats brand: the app icon (Nick's pick 2026-10-20, concept D of scripts/icon-concepts-2.swift: three brisket slices on pink
// butcher paper, on flag blue), in the shared Eats Ranked style (../state-prompts/ICON-STYLE.md; check with --emblem, the paper is the
// backing shape). Usage, from tx-eats/: swift scripts/make-brand.swift   -> TexasEats/Resources/Assets.xcassets/AppIcon.appiconset/icon-1024.png
// and the website's icons (docs/icon-512.png, icon-192.png, apple-touch-icon.png, favicon-32.png) and share image (docs/og.png).
import AppKit
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

func rgb(_ hex: UInt32) -> CGColor {
    CGColor(srgbRed: CGFloat((hex >> 16) & 255) / 255, green: CGFloat((hex >> 8) & 255) / 255, blue: CGFloat(hex & 255) / 255, alpha: 1)
}
let BLUE: UInt32 = 0x002868
let BARK: UInt32 = 0x3A2318, RING: UInt32 = 0xD9574A, MEAT: UInt32 = 0xC98A5E, MEAT2: UInt32 = 0xA9683F, PAPER: UInt32 = 0xE7B9A6

/// One brisket slice lying flat: black-pepper bark along the top edge, the pink smoke ring under it, meat, a darker lower edge.
func slice(_ c: CGContext, _ r: CGRect, _ s: CGFloat, ring: UInt32?) {
    let p = CGPath(roundedRect: r, cornerWidth: 0.05 * s, cornerHeight: 0.05 * s, transform: nil)
    if let ring { c.setStrokeColor(rgb(ring)); c.setLineWidth(0.0254 * s); c.setLineJoin(.round); c.addPath(p); c.strokePath() }
    c.saveGState(); c.addPath(p); c.clip()
    c.setFillColor(rgb(MEAT)); c.fill(r)
    c.setFillColor(rgb(MEAT2)); c.fill(CGRect(x: r.minX, y: r.minY, width: r.width, height: r.height * 0.28))
    c.setFillColor(rgb(RING)); c.fill(CGRect(x: r.minX, y: r.maxY - 0.085 * s, width: r.width, height: 0.085 * s))
    c.setFillColor(rgb(BARK)); c.fill(CGRect(x: r.minX, y: r.maxY - 0.05 * s, width: r.width, height: 0.05 * s))
    c.restoreGState()
}

/// The food on its paper: a sheet of pink butcher paper (0.73 x 0.47, centred) with three brisket slices shingled left to right,
/// each ringed in the paper colour where it overlaps the next. Paints nothing behind the paper.
func brisket(_ c: CGContext, _ s: CGFloat) {
    c.setFillColor(rgb(PAPER)); c.fill(CGRect(x: 0.135 * s, y: 0.27 * s, width: 0.73 * s, height: 0.47 * s))
    for x in [0.19, 0.36, 0.53] as [CGFloat] {
        slice(c, CGRect(x: x * s, y: 0.33 * s, width: 0.28 * s, height: 0.34 * s), s, ring: PAPER)
    }
}

func render(_ n: Int, _ path: String, background: Bool) {
    let ctx = CGContext(data: nil, width: n, height: n, bitsPerComponent: 8, bytesPerRow: 0, space: CGColorSpace(name: CGColorSpace.sRGB)!,
                        bitmapInfo: background ? CGImageAlphaInfo.noneSkipLast.rawValue : CGImageAlphaInfo.premultipliedLast.rawValue)!
    ctx.setShouldAntialias(true)
    if background { ctx.setFillColor(rgb(BLUE)); ctx.fill(CGRect(x: 0, y: 0, width: n, height: n)) }
    brisket(ctx, CGFloat(n))
    let d = CGImageDestinationCreateWithURL(URL(fileURLWithPath: path) as CFURL, UTType.png.identifier as CFString, 1, nil)!
    CGImageDestinationAddImage(d, ctx.makeImage()!, nil)
    guard CGImageDestinationFinalize(d) else { fatalError("could not write \(path)") }
    print("wrote", path)
}
render(1024, "TexasEats/Resources/Assets.xcassets/AppIcon.appiconset/icon-1024.png", background: true)
try? FileManager.default.createDirectory(atPath: "docs", withIntermediateDirectories: true)
for (n, name) in [(512, "icon-512.png"), (192, "icon-192.png"), (180, "apple-touch-icon.png"), (32, "favicon-32.png")] {
    render(n, "docs/" + name, background: true)
}

/// The share image (1200 x 630): flag blue, the brisket on its paper at the left, the name and tagline at the right, the flag's
/// white and red as a band along the bottom.
func og(_ path: String) {
    let W = 1200, H = 630
    let ctx = CGContext(data: nil, width: W, height: H, bitsPerComponent: 8, bytesPerRow: 0, space: CGColorSpace(name: CGColorSpace.sRGB)!,
                        bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)!
    ctx.setShouldAntialias(true)
    ctx.setFillColor(rgb(BLUE)); ctx.fill(CGRect(x: 0, y: 0, width: W, height: H))
    ctx.setFillColor(CGColor(srgbRed: 1, green: 1, blue: 1, alpha: 1)); ctx.fill(CGRect(x: 0, y: 28, width: W, height: 14))
    ctx.setFillColor(rgb(0xBF0A30)); ctx.fill(CGRect(x: 0, y: 0, width: W, height: 28))
    ctx.saveGState(); ctx.translateBy(x: 30, y: 60); brisket(ctx, 540); ctx.restoreGState()
    let ns = NSGraphicsContext(cgContext: ctx, flipped: false)
    NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = ns
    let title = NSFont(name: "AvenirNextCondensed-Heavy", size: 118) ?? NSFont.boldSystemFont(ofSize: 110)
    let sub = NSFont(name: "AvenirNextCondensed-DemiBold", size: 44) ?? NSFont.boldSystemFont(ofSize: 40)
    NSAttributedString(string: "TEXAS EATS", attributes: [.font: title, .foregroundColor: NSColor.white]).draw(at: NSPoint(x: 590, y: 330))
    NSAttributedString(string: "BBQ, TEX-MEX & TAQUERÍAS", attributes: [.font: sub, .foregroundColor: NSColor(srgbRed: 0.97, green: 0.86, blue: 0.89, alpha: 1)]).draw(at: NSPoint(x: 594, y: 270))
    NSGraphicsContext.restoreGraphicsState()
    let d = CGImageDestinationCreateWithURL(URL(fileURLWithPath: path) as CFURL, UTType.png.identifier as CFString, 1, nil)!
    CGImageDestinationAddImage(d, ctx.makeImage()!, nil)
    guard CGImageDestinationFinalize(d) else { fatalError("could not write \(path)") }
    print("wrote", path)
}
og("docs/og.png")

// Texas Eats icon, round 2 (Nick 2026-10-20: "new icon" after picking brisket). Eats Ranked style v1 (../state-prompts/ICON-STYLE.md).
// Usage: swift scripts/icon-concepts-2.swift <outdir>  -> tx-D-paper.png, tx-E-slab.png, tx-F-rib.png (1024, flag blue)
import AppKit
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

func rgb(_ hex: UInt32) -> CGColor {
    CGColor(srgbRed: CGFloat((hex >> 16) & 255) / 255, green: CGFloat((hex >> 8) & 255) / 255, blue: CGFloat(hex & 255) / 255, alpha: 1)
}
let BLUE: UInt32 = 0x002868
let BARK: UInt32 = 0x3A2318, RING: UInt32 = 0xD9574A, MEAT: UInt32 = 0xC98A5E, MEAT2: UInt32 = 0xA9683F, PAPER: UInt32 = 0xE7B9A6

/// One brisket slice lying flat, seen from above: bark around the top edge, smoke ring under it, meat, darker lower edge.
func slice(_ c: CGContext, _ r: CGRect, _ s: CGFloat, ring: UInt32?) {
    let p = CGPath(roundedRect: r, cornerWidth: 0.05 * s, cornerHeight: 0.05 * s, transform: nil)
    if let ring { c.setStrokeColor(rgb(ring)); c.setLineWidth(26); c.setLineJoin(.round); c.addPath(p); c.strokePath() }
    c.saveGState(); c.addPath(p); c.clip()
    c.setFillColor(rgb(MEAT)); c.fill(r)
    c.setFillColor(rgb(MEAT2)); c.fill(CGRect(x: r.minX, y: r.minY, width: r.width, height: r.height * 0.28))
    c.setFillColor(rgb(RING)); c.fill(CGRect(x: r.minX, y: r.maxY - 0.085 * s, width: r.width, height: 0.085 * s))
    c.setFillColor(rgb(BARK)); c.fill(CGRect(x: r.minX, y: r.maxY - 0.05 * s, width: r.width, height: 0.05 * s))
    c.restoreGState()
}

/// D: three brisket slices shingled left to right on a sheet of pink butcher paper (the backing shape, like Chicago's star).
func paper(_ c: CGContext, _ s: CGFloat) {
    c.setFillColor(rgb(PAPER)); c.fill(CGRect(x: 0.135 * s, y: 0.27 * s, width: 0.73 * s, height: 0.47 * s))
    for (i, x) in [0.19, 0.36, 0.53].enumerated() {
        slice(c, CGRect(x: x * s, y: (0.33 + CGFloat(i) * 0.0) * s, width: 0.28 * s, height: 0.34 * s), s, ring: PAPER)
    }
}

/// E: a whole slab of brisket in side elevation with two slices cut from its right end, the cuts showing as background gaps.
func slab(_ c: CGContext, _ s: CGFloat) {
    slice(c, CGRect(x: 0.14 * s, y: 0.32 * s, width: 0.42 * s, height: 0.36 * s), s, ring: nil)
    slice(c, CGRect(x: 0.59 * s, y: 0.32 * s, width: 0.12 * s, height: 0.36 * s), s, ring: nil)
    slice(c, CGRect(x: 0.74 * s, y: 0.32 * s, width: 0.12 * s, height: 0.36 * s), s, ring: nil)
}

/// F: a beef rib ("dino rib"), side elevation, level: a thick slab of black-bark rib meat cut open at the left, so the cut face shows
/// pink smoke ring around juicy meat, and a long bone running out of the right end to a round knob.
func rib(_ c: CGContext, _ s: CGFloat) {
    c.setLineCap(.round)
    c.setStrokeColor(rgb(0xF1E4CC)); c.setLineWidth(0.10 * s)
    c.move(to: CGPoint(x: 0.55 * s, y: 0.50 * s)); c.addLine(to: CGPoint(x: 0.80 * s, y: 0.50 * s)); c.strokePath()
    c.setFillColor(rgb(0xF1E4CC)); c.fillEllipse(in: CGRect(x: 0.76 * s, y: 0.42 * s, width: 0.10 * s, height: 0.16 * s))
    let m = CGRect(x: 0.14 * s, y: 0.33 * s, width: 0.52 * s, height: 0.34 * s)
    c.setFillColor(rgb(BARK)); c.addPath(CGPath(roundedRect: m, cornerWidth: 0.11 * s, cornerHeight: 0.11 * s, transform: nil)); c.fillPath()
    // cut face at the left end: smoke ring, then meat
    c.setFillColor(rgb(RING)); c.fillEllipse(in: CGRect(x: 0.175 * s, y: 0.36 * s, width: 0.22 * s, height: 0.28 * s))
    c.setFillColor(rgb(MEAT)); c.fillEllipse(in: CGRect(x: 0.205 * s, y: 0.395 * s, width: 0.16 * s, height: 0.21 * s))
}

let out = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "."
func render(_ name: String, _ f: (CGContext, CGFloat) -> Void) {
    let ctx = CGContext(data: nil, width: 1024, height: 1024, bitsPerComponent: 8, bytesPerRow: 0, space: CGColorSpace(name: CGColorSpace.sRGB)!,
                        bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)!
    ctx.setShouldAntialias(true); ctx.setFillColor(rgb(BLUE)); ctx.fill(CGRect(x: 0, y: 0, width: 1024, height: 1024))
    f(ctx, 1024)
    let d = CGImageDestinationCreateWithURL(URL(fileURLWithPath: out + "/" + name) as CFURL, UTType.png.identifier as CFString, 1, nil)!
    CGImageDestinationAddImage(d, ctx.makeImage()!, nil); CGImageDestinationFinalize(d)
}
render("tx-D-paper.png", paper); render("tx-E-slab.png", slab); render("tx-F-rib.png", rib)
print("ok")

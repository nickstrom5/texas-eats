// Texas Eats icon concepts, Eats Ranked style v1 (../state-prompts/ICON-STYLE.md): three foods, each flat, level and centred on a
// plain Texas-flag background. Usage: swift scripts/icon-concepts.swift <outdir>  (writes tx-A-brisket.png, tx-B-taco.png,
// tx-C-kolache.png at 1024). Nick picks one; the pick moves into scripts/make-brand.swift with its food function.
import AppKit
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

func rgb(_ hex: UInt32) -> CGColor {
    CGColor(srgbRed: CGFloat((hex >> 16) & 255) / 255, green: CGFloat((hex >> 8) & 255) / 255, blue: CGFloat(hex & 255) / 255, alpha: 1)
}
let BLUE: UInt32 = 0x002868, RED: UInt32 = 0xBF0A30

/// A: three slices of brisket standing side by side, front view, level: each slice has a black-pepper bark cap, the pink
/// smoke ring under it, then the meat in two flat tones (lighter body, darker underside). The middle slice stands a little taller
/// and in front; a 13 px ring in the background blue separates the overlapping slices (R7).
func brisket(_ c: CGContext, _ s: CGFloat) {
    func slice(_ x: CGFloat, _ y: CGFloat, _ w: CGFloat, _ h: CGFloat) {
        let r = CGRect(x: x * s, y: y * s, width: w * s, height: h * s)
        let path = CGPath(roundedRect: r, cornerWidth: 0.055 * s, cornerHeight: 0.055 * s, transform: nil)
        c.setLineJoin(.round); c.setStrokeColor(rgb(BLUE)); c.setLineWidth(26); c.addPath(path); c.strokePath()
        c.saveGState(); c.addPath(path); c.clip()
        c.setFillColor(rgb(0xC98A5E)); c.fill(r)
        c.setFillColor(rgb(0xA9683F)); c.fill(CGRect(x: r.minX, y: r.minY, width: r.width, height: r.height * 0.30))
        c.setFillColor(rgb(0xD9574A)); c.fill(CGRect(x: r.minX, y: r.maxY - 0.095 * s, width: r.width, height: 0.095 * s))
        c.setFillColor(rgb(0x3A2318)); c.fill(CGRect(x: r.minX, y: r.maxY - 0.055 * s, width: r.width, height: 0.055 * s))
        c.restoreGState()
    }
    slice(0.140, 0.285, 0.27, 0.40)
    slice(0.590, 0.285, 0.27, 0.40)
    slice(0.355, 0.285, 0.29, 0.45)
}

/// B: a crispy taco in side elevation, level: a golden half-round shell, a band of seasoned meat along its open top, lettuce
/// heaped over the meat, and three tomato dots cut through to the background red.
func taco(_ c: CGContext, _ s: CGFloat) {
    func p(_ x: CGFloat, _ y: CGFloat) -> CGPoint { CGPoint(x: x * s, y: y * s) }
    func cap(_ x: CGFloat, _ y: CGFloat, _ w: CGFloat, _ h: CGFloat, _ hex: UInt32) {
        c.setFillColor(rgb(hex)); c.addPath(CGPath(roundedRect: CGRect(x: x * s, y: y * s, width: w * s, height: h * s), cornerWidth: h / 2 * s, cornerHeight: h / 2 * s, transform: nil)); c.fillPath()
    }
    cap(0.21, 0.575, 0.33, 0.17, 0x5DAE4B)      // lettuce, two heaps
    cap(0.46, 0.590, 0.33, 0.17, 0x5DAE4B)
    cap(0.15, 0.555, 0.70, 0.11, 0x6B3518)      // meat along the rim
    let shell = CGMutablePath()
    shell.move(to: p(0.14, 0.575))
    shell.addArc(center: p(0.50, 0.575), radius: 0.36 * s, startAngle: .pi, endAngle: 0, clockwise: false)
    shell.closeSubpath()
    c.setFillColor(rgb(0xF2C14E)); c.addPath(shell); c.fillPath()
    c.setFillColor(rgb(RED))
    for (x, y) in [(0.31, 0.665), (0.50, 0.690), (0.68, 0.675)] as [(CGFloat, CGFloat)] {
        c.fillEllipse(in: CGRect(x: (x - 0.025) * s, y: y * s, width: 0.05 * s, height: 0.05 * s))
    }
}

/// C: a fruit kolache from straight above: a pillowy, squarish golden bun (rounded rectangle, 0.71 x 0.56), a lighter raised rim,
/// a round apricot well and four cream posypka crumbs on the filling.
func kolache(_ c: CGContext, _ s: CGFloat) {
    func rr(_ w: CGFloat, _ h: CGFloat, _ rad: CGFloat, _ cy: CGFloat, _ hex: UInt32) {
        c.setFillColor(rgb(hex)); c.addPath(CGPath(roundedRect: CGRect(x: (0.5 - w / 2) * s, y: (cy - h / 2) * s, width: w * s, height: h * s), cornerWidth: rad * s, cornerHeight: rad * s, transform: nil)); c.fillPath()
    }
    rr(0.71, 0.55, 0.22, 0.465, 0xD9973F)   // underside shows as a band along the bottom
    rr(0.71, 0.54, 0.22, 0.48, 0xE9B05A)    // bun
    rr(0.53, 0.40, 0.16, 0.48, 0xF4CC85)    // raised rim
    c.setFillColor(rgb(0xF28C28)); c.fillEllipse(in: CGRect(x: 0.335 * s, y: 0.315 * s, width: 0.33 * s, height: 0.33 * s))
    c.setFillColor(rgb(0xFBEFD6))
    for (x, y) in [(0.44, 0.53), (0.56, 0.54), (0.47, 0.42), (0.58, 0.43)] as [(CGFloat, CGFloat)] {
        c.fillEllipse(in: CGRect(x: (x - 0.024) * s, y: (y - 0.024) * s, width: 0.048 * s, height: 0.048 * s))
    }
}

let out = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "."
func render(_ name: String, _ bg: UInt32, _ f: (CGContext, CGFloat) -> Void) {
    let n = 1024
    let ctx = CGContext(data: nil, width: n, height: n, bitsPerComponent: 8, bytesPerRow: 0, space: CGColorSpace(name: CGColorSpace.sRGB)!,
                        bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)!
    ctx.setShouldAntialias(true)
    ctx.setFillColor(rgb(bg)); ctx.fill(CGRect(x: 0, y: 0, width: n, height: n))
    f(ctx, CGFloat(n))
    let url = URL(fileURLWithPath: out + "/" + name) as CFURL
    let d = CGImageDestinationCreateWithURL(url, UTType.png.identifier as CFString, 1, nil)!
    CGImageDestinationAddImage(d, ctx.makeImage()!, nil); CGImageDestinationFinalize(d)
    print("wrote", out + "/" + name)
}
render("tx-A-brisket.png", BLUE, brisket)
render("tx-B-taco.png", RED, taco)
render("tx-C-kolache.png", BLUE, kolache)

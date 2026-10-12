// Ballon vectoriel dessiné avec AppKit, sans dépendance supplémentaire.
import AppKit

let destination = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
try FileManager.default.createDirectory(at: destination, withIntermediateDirectories: true)
let green = NSColor(srgbRed: 19/255, green: 43/255, blue: 39/255, alpha: 1)
let panels = NSColor(srgbRed: 37/255, green: 77/255, blue: 61/255, alpha: 1)
let white = NSColor(srgbRed: 246/255, green: 249/255, blue: 241/255, alpha: 1)
func point(_ center: CGPoint, _ radius: Double, _ angle: Double) -> CGPoint {
    CGPoint(x: center.x + radius * cos(angle), y: center.y + radius * sin(angle))
}
func pentagon(_ center: CGPoint, _ radius: Double, _ angle: Double) -> NSBezierPath {
    let path = NSBezierPath()
    for i in 0..<5 {
        let vertex = point(center, radius, angle + Double(i) * 2 * .pi / 5)
        if i == 0 { path.move(to: vertex) } else { path.line(to: vertex) }
    }
    path.close(); return path
}
func render(_ pixels: Int) -> Data {
    let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: pixels, pixelsHigh: pixels, bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    let graphics = NSGraphicsContext(bitmapImageRep: bitmap)!
    NSGraphicsContext.current = graphics
    let context = graphics.cgContext
    context.scaleBy(x: Double(pixels)/128, y: Double(pixels)/128)
    context.translateBy(x: 0, y: 128); context.scaleBy(x: 1, y: -1)
    green.setFill()
    NSBezierPath(roundedRect: NSRect(x: 8, y: 8, width: 112, height: 112), xRadius: 25, yRadius: 25).fill()
    let ball = NSBezierPath(ovalIn: NSRect(x: 24, y: 24, width: 80, height: 80))
    white.setFill(); ball.fill()
    NSGraphicsContext.saveGraphicsState(); ball.addClip(); panels.setFill()
    let center = CGPoint(x: 64, y: 64)
    pentagon(center, 14, -.pi/2).fill()
    for i in 0..<5 {
        let angle = -.pi/2 + Double(i)*2 * .pi/5
        pentagon(point(center, 34, angle), 10, angle - .pi/2).fill()
    }
    NSGraphicsContext.restoreGraphicsState()
    panels.setStroke()
    for i in 0..<5 {
        let angle = -.pi/2 + Double(i)*2 * .pi/5
        let seam = NSBezierPath(); seam.move(to: point(center,14,angle)); seam.line(to: point(center,29,angle)); seam.lineWidth=1.5; seam.stroke()
    }
    NSGraphicsContext.restoreGraphicsState()
    return bitmap.representation(using: .png, properties: [:])!
}
for size in [16, 32, 128, 256, 512] {
    try render(size).write(to: destination.appendingPathComponent("icon_\(size)x\(size).png"))
    try render(size*2).write(to: destination.appendingPathComponent("icon_\(size)x\(size)@2x.png"))
}

import AppKit
import Foundation

let config = try JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))) as! [String: Any]
let frames = config["frames"] as! [[String: Any]]
let output = URL(fileURLWithPath: CommandLine.arguments[2], isDirectory: true)
try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
let font = NSFont.monospacedSystemFont(ofSize: 20, weight: .regular)
let charWidth = ("M" as NSString).size(withAttributes: [.font:font]).width
for (index, frame) in frames.enumerated() {
  autoreleasepool {
    let screen = frame["screen"] as! [String: Any]
    let lines = screen["lines"] as! [String]
    let bitmap = NSBitmapImageRep(bitmapDataPlanes:nil, pixelsWide:1600, pixelsHigh:1000, bitsPerSample:8, samplesPerPixel:4, hasAlpha:true, isPlanar:false, colorSpaceName:.deviceRGB, bytesPerRow:0, bitsPerPixel:0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep:bitmap)
    NSColor(calibratedRed:0.035,green:0.045,blue:0.065,alpha:1).setFill()
    NSBezierPath(rect:NSRect(x:0,y:0,width:1600,height:1000)).fill()
    let style = NSMutableParagraphStyle(); style.lineBreakMode = .byClipping
    let attributes: [NSAttributedString.Key:Any] = [.font:font,.foregroundColor:NSColor(white:0.92,alpha:1),.paragraphStyle:style]
    for (row,line) in lines.enumerated() {
      (line as NSString).draw(in:NSRect(x:48,y:900-row*25,width:1504,height:26),withAttributes:attributes)
    }
    let headerAttributes: [NSAttributedString.Key:Any] = [.font:NSFont.systemFont(ofSize:17,weight:.medium),.foregroundColor:NSColor.systemTeal]
    ("ТЕРМИНАЛ · фактический ввод и вывод CLI · без слайдов" as NSString).draw(at:NSPoint(x:48,y:958),withAttributes:headerAttributes)
    let time = frame["time"] as! Double
    (String(format:"%02d:%02d",Int(time)/60,Int(time)%60) as NSString).draw(at:NSPoint(x:1470,y:958),withAttributes:headerAttributes)
    let x = screen["x"] as! Int, y = screen["y"] as! Int
    NSColor.systemTeal.setFill()
    let cursorX: CGFloat = 48.0 + CGFloat(x) * charWidth
    let cursorY: CGFloat = CGFloat(900 - y * 25)
    NSBezierPath(rect:NSRect(x:cursorX,y:cursorY,width:charWidth,height:2)).fill()
    ("Записанная PTY-сессия · скорость 1× · synthetic_fixture · не запись рабочего стола" as NSString).draw(at:NSPoint(x:48,y:30),withAttributes:[.font:NSFont.systemFont(ofSize:15),.foregroundColor:NSColor.gray])
    NSGraphicsContext.restoreGraphicsState()
    let data = bitmap.representation(using:.png,properties:[:])!
    try! data.write(to:output.appendingPathComponent(String(format:"%05d.png",index)))
  }
}
print("Rendered \(frames.count) actual timed terminal states")

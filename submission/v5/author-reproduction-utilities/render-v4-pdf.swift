import AppKit
import CoreGraphics
import Foundation

let input = URL(fileURLWithPath: CommandLine.arguments[1])
let output = URL(fileURLWithPath: CommandLine.arguments[2])
let edition = CommandLine.arguments.count > 3 ? CommandLine.arguments[3] : "v4"
if FileManager.default.fileExists(atPath: output.path) { fatalError("Preserve existing PDF") }
let sourcePages = try JSONSerialization.jsonObject(with: Data(contentsOf: input)) as! [[String: String]]
var box = CGRect(x: 0, y: 0, width: 842, height: 595)
let context = CGContext(consumer: CGDataConsumer(url: output as CFURL)!, mediaBox: &box, nil)!
let style = NSMutableParagraphStyle()
style.lineSpacing = 4
style.paragraphSpacing = 6
style.lineBreakMode = .byWordWrapping
func face(_ size: CGFloat, _ bold: Bool = false) -> NSFont {
    guard let font = NSFont(name:bold ? "Arial-BoldMT" : "ArialMT",size:size) else { fatalError("Pinned PDF font unavailable") }
    return font
}
func height(_ text: String, _ size: CGFloat = 12, _ bold: Bool = false) -> CGFloat {
    return (text as NSString).boundingRect(with: CGSize(width:758,height:10000),
        options:[.usesLineFragmentOrigin,.usesFontLeading],
        attributes:[.font:face(size,bold),.paragraphStyle:style]).height
}
var pages = [[String:String]]()
for original in sourcePages {
    var remaining = original["body"]!
    var part = 0
    while !remaining.isEmpty {
        var page = original
        if part > 0 { page.removeValue(forKey:"image"); page.removeValue(forKey:"caption") }
        let cap: CGFloat = (page["image"] ?? "").isEmpty ? 430 : 210
        let ns = remaining as NSString
        var low = 1, high = ns.length
        while low < high {
            let mid = (low + high + 1) / 2
            if height(ns.substring(to:mid)) <= cap { low = mid } else { high = mid - 1 }
        }
        var end = low
        if end < ns.length {
            let paragraph = ns.range(of:"\n\n",options:.backwards,range:NSRange(location:0,length:end))
            if paragraph.location != NSNotFound && paragraph.location > end/3 { end = paragraph.location }
            let space = ns.rangeOfCharacter(from:.whitespacesAndNewlines,options:.backwards,range:NSRange(location:0,length:end))
            if paragraph.location == NSNotFound || paragraph.location <= low/3 {
                if space.location != NSNotFound { end = space.location }
            }
        }
        if end == 0 { fatalError("Unbreakable body text") }
        page["body"] = ns.substring(to:end)
        if part > 0 { page["title"] = original["title"]! + " (далее)" }
        pages.append(page)
        remaining = ns.substring(from:end).trimmingCharacters(in:.whitespacesAndNewlines)
        part += 1
    }
}
func draw(_ text: String, _ rect: CGRect, _ size: CGFloat, _ bold: Bool = false) {
    let attributes: [NSAttributedString.Key: Any] = [
        .font: face(size,bold),
        .paragraphStyle: style, .foregroundColor: NSColor(calibratedWhite: 0.12, alpha: 1)]
    let actual = (text as NSString).boundingRect(with: CGSize(width: rect.width, height: 10000),
        options: [.usesLineFragmentOrigin, .usesFontLeading], attributes: attributes).height
    if actual > rect.height + 1 { fatalError("Text overflow \(actual)>\(rect.height): \(text.prefix(80))") }
    (text as NSString).draw(in: rect, withAttributes: attributes)
}
for (i, page) in pages.enumerated() {
    context.beginPDFPage(nil)
    NSGraphicsContext.current = NSGraphicsContext(cgContext: context, flipped: false)
    NSColor.white.setFill(); NSBezierPath(rect: box).fill()
    draw("СТРАТЕГ · \(edition) · локальный демонстрационный комплект", CGRect(x:42,y:552,width:758,height:24), 11, true)
    var titleSize: CGFloat = 23
    while height(page["title"]!,titleSize,true) > 40 && titleSize > 12 { titleSize -= 1 }
    draw(page["title"]!, CGRect(x:42,y:507,width:758,height:40), titleSize, true)
    let imagePath = page["image"] ?? ""
    if imagePath.isEmpty {
        draw(page["body"]!, CGRect(x:42,y:65,width:758,height:430), 12)
        if page["title"] == "Архитектура и слои контекста" {
            let labels = ["Запрос", "Host LLM", "SRC → EXT", "CLM / CAL", "OPT → STR", "H / pending"]
            for (j,label) in labels.enumerated() {
                let x = CGFloat(42 + j*128)
                NSColor(calibratedRed:0.1,green:0.45,blue:0.45,alpha:1).setStroke()
                NSBezierPath(roundedRect:CGRect(x:x,y:92,width:116,height:52),xRadius:6,yRadius:6).stroke()
                draw(label,CGRect(x:x+8,y:104,width:102,height:27),11,true)
                if j < labels.count-1 { draw("→",CGRect(x:x+117,y:105,width:15,height:25),12) }
            }
        }
    } else {
        draw(page["body"]!, CGRect(x:42,y:287,width:758,height:210), 12)
        let image = NSImage(contentsOfFile: imagePath)!
        let scale = min(758.0 / image.size.width, 200.0 / image.size.height)
        image.draw(in: CGRect(x:42,y:75,width:image.size.width * scale,height:image.size.height * scale), from:.zero, operation:.sourceOver, fraction:1)
        draw(page["caption"] ?? "Фрагмент реального PTY, не макет.", CGRect(x:42,y:40,width:758,height:32), 9)
    }
    let status = edition == "v4" ? "не опубликовано/не отправлено" : "юридическая отправка отдельно"
    draw("Синтетические данные · business-H pending · \(status) · \(i+1)/\(pages.count)",
         CGRect(x:42,y:15,width:758,height:21), 9)
    context.endPDFPage()
}
context.closePDF()
print("Created \(pages.count) checked landscape pages")

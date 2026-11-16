import Foundation
import NaturalLanguage

let raw = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))
let texts = try JSONSerialization.jsonObject(with: raw) as! [String]
if let model = NLEmbedding.sentenceEmbedding(for: .english) {
    let vectors = texts.map { model.vector(for: $0) ?? [] }
    let result: [String: Any] = ["model": "Apple-NaturalLanguage-English-sentence", "revision": model.revision, "dimension": model.dimension, "vectors": vectors]
    let data = try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
    FileHandle.standardOutput.write(data)
} else {
    let data = try JSONSerialization.data(withJSONObject: ["unavailable": true])
    FileHandle.standardOutput.write(data)
}

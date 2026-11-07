// Réponse à un message privé du client League : réponses rapides directement
// dans la notification, ou « Répondre… » qui ouvre cet écran (réponses rapides +
// dictée / gribouillage / clavier). Envoi : action `chat_reply` du Pi → agent →
// LCU. (Pas de champ de texte DANS la notification : indisponible sur watchOS.)
import SwiftUI
import UserNotifications
import WatchKit

enum QuickReplies {
    static let all = ["J'arrive !", "2 min", "Pas dispo", "Ok 👍"]
    static let inNotification = 3          // les premières, en boutons de notification
}

struct ReplyTarget: Identifiable {
    let conversationId: String
    let from: String
    var id: String { conversationId }
}

/// Conversation à laquelle répondre (posée par « Répondre… » d'une notification).
@MainActor
final class ReplyCenter: ObservableObject {
    static let shared = ReplyCenter()
    @Published var target: ReplyTarget?
}

/// Envoie la réponse ; true si le Pi l'a prise en charge.
func sendReply(_ text: String, to conversationId: String) async -> Bool {
    await postToPi("/action", ["action": "chat_reply", "conversationId": conversationId,
                               "body": text]) == 200
}

/// Échec d'une réponse envoyée depuis la notification (app fermée) : on le dit.
func notifyReplyFailed(to from: String) {
    let content = UNMutableNotificationContent()
    content.title = "Réponse non envoyée"
    content.body = from.isEmpty ? "PC ou Pi injoignable" : "À \(from) : PC ou Pi injoignable"
    UNUserNotificationCenter.current().add(
        UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil))
}

struct ReplyView: View {
    let target: ReplyTarget
    @Environment(\.dismiss) private var dismiss
    @State private var text = ""
    @State private var sending = false
    @State private var failed = false

    var body: some View {
        NavigationStack {
            List {
                Section {
                    ForEach(QuickReplies.all, id: \.self) { reply in
                        Button(reply) { send(reply) }
                    }
                }
                Section {
                    TextField("Écrire…", text: $text)
                        .onSubmit { send(text) }
                } footer: {
                    if failed {
                        Label("Non envoyé : PC ou Pi injoignable", systemImage: "exclamationmark.triangle.fill")
                    } else if sending {
                        Label("Envoi…", systemImage: "paperplane")
                    }
                }
            }
            .disabled(sending)
            .navigationTitle(target.from.isEmpty ? "Répondre" : "À \(target.from)")
        }
    }

    private func send(_ reply: String) {
        let body = reply.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !body.isEmpty else { return }
        sending = true
        failed = false
        Task {
            let ok = await sendReply(body, to: target.conversationId)
            sending = false
            if ok {
                WKInterfaceDevice.current().play(.success)
                dismiss()
            } else {
                failed = true
                WKInterfaceDevice.current().play(.failure)
            }
        }
    }
}

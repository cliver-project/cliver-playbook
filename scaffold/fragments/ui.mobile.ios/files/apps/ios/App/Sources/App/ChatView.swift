import Core
import SwiftUI

/// Chat-first surface. It is a thin renderer of the API's typed run events:
/// the UI never chooses an agent and never calls a model provider.
struct ChatView: View {
    let onOpenProducts: (() -> Void)?

    @Environment(AuthStore.self) private var session
    @Environment(\.appComponents) private var components

    @State private var messages: [ChatEntry] = []
    @State private var tools: [ToolEntry] = []
    @State private var input = ""
    @State private var busy = false
    @State private var error: String?
    @State private var selectedAgent: String?
    @State private var runID: String?
    @State private var runTask: Task<Void, Never>?
    @State private var feedbackTarget: FeedbackTarget?
    @State private var feedbackRating: Int?
    @State private var feedbackError: String?

    var body: some View {
        VStack(spacing: 0) {
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 12) {
                        if messages.isEmpty {
                            Text("Ask about products, your account, or this app.")
                                .font(.subheadline)
                                .foregroundStyle(.secondary)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                        ForEach(messages) { message in
                            let text = message.text.isEmpty && busy
                                ? "Thinking…"
                                : message.text
                            if !text.isEmpty {
                                components.chatMessage(message.isUser, text)
                                    .id(message.id)
                            }
                        }
                        ForEach(tools) { tool in
                            components.toolCall(
                                tool.isError ? "\(tool.name) (error)" : tool.name,
                                tool.detail
                            )
                        }
                        if feedbackTarget != nil, !busy {
                            components.feedbackButtons(feedbackRating, rate)
                            if let feedbackError {
                                Text(feedbackError)
                                    .font(.footnote)
                                    .foregroundStyle(.red)
                            }
                        }
                        if let error {
                            Text(error)
                                .font(.footnote)
                                .foregroundStyle(.red)
                        }
                    }
                    .padding()
                }
                .onChange(of: messages.count) { _, _ in
                    if let last = messages.last {
                        withAnimation {
                            proxy.scrollTo(last.id, anchor: .bottom)
                        }
                    }
                }
            }

            if selectedAgent == "products", let onOpenProducts {
                Button("Open products", action: onOpenProducts)
                    .buttonStyle(.bordered)
                    .padding(.bottom, DesignSystem.Spacing.s)
            }

            components.composer($input, busy, send, stop)
                .padding()
        }
        .onDisappear {
            runTask?.cancel()
            if let runID {
                Task {
                    try? await session.api.cancelAgentRun(runID: runID)
                }
            }
        }
    }

    private func send() {
        let text = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !busy else { return }

        input = ""
        error = nil
        selectedAgent = nil
        tools = []
        busy = true
        feedbackTarget = nil
        feedbackRating = nil
        feedbackError = nil
        messages.append(ChatEntry(isUser: true, text: text))
        let assistantID = UUID()
        messages.append(ChatEntry(id: assistantID, isUser: false, text: ""))

        runTask = Task { @MainActor in
            var runAgent = "general"
            do {
                let id = try await session.api.startAgentRun(message: text)
                runID = id
                for try await event in session.api.streamAgentRun(runID: id) {
                    if event.type == "agent.selected" {
                        runAgent = event.agent ?? "general"
                    }
                    apply(event, assistantID: assistantID)
                    if event.type == "run.completed" {
                        feedbackTarget = FeedbackTarget(runID: id, agent: runAgent)
                    }
                }
            } catch is CancellationError {
                // The user stopped the run or left the screen.
            } catch {
                self.error = error.localizedDescription
            }
            busy = false
            runID = nil
        }
    }

    private func stop() {
        runTask?.cancel()
        if let runID {
            Task {
                try? await session.api.cancelAgentRun(runID: runID)
            }
        }
        busy = false
    }

    private func rate(_ rating: Int) {
        guard let feedbackTarget else { return }
        feedbackError = nil
        Task { @MainActor in
            do {
                try await session.api.submitAgentFeedback(
                    runID: feedbackTarget.runID,
                    agent: feedbackTarget.agent,
                    rating: rating
                )
                feedbackRating = rating
            } catch {
                feedbackError = error.localizedDescription
            }
        }
    }

    private func apply(_ event: AgentEvent, assistantID: UUID) {
        switch event.type {
        case "agent.selected":
            selectedAgent = event.agent
        case "message.delta":
            guard let index = messages.firstIndex(where: { $0.id == assistantID }) else {
                return
            }
            messages[index].text += event.delta ?? ""
        case "tool.call":
            tools.append(
                ToolEntry(
                    id: event.toolCallID ?? UUID().uuidString,
                    name: event.name ?? "tool",
                    detail: event.arguments ?? ""
                )
            )
        case "tool.result":
            guard
                let toolCallID = event.toolCallID,
                let index = tools.firstIndex(where: { $0.id == toolCallID })
            else {
                return
            }
            tools[index].detail = event.result ?? ""
            tools[index].isError = event.isError
        case "run.failed":
            error = event.message ?? "The run failed."
        default:
            break
        }
    }
}

private struct ChatEntry: Identifiable {
    let id: UUID
    let isUser: Bool
    var text: String

    init(id: UUID = UUID(), isUser: Bool, text: String) {
        self.id = id
        self.isUser = isUser
        self.text = text
    }
}

private struct ToolEntry: Identifiable {
    let id: String
    let name: String
    var detail: String
    var isError = false
}

private struct FeedbackTarget {
    let runID: String
    let agent: String
}

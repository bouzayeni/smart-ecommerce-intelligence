import { Card, PageHeader } from "../components/ui";

/** Placeholder until Phase 11 adds POST /api/assistant/query. Nothing here is simulated. */
export default function AssistantPage() {
  return (
    <>
      <PageHeader title="AI business assistant"
        description="Ask questions about the warehouse in plain language. Answers will cite the metric, date range and filters they used." />
      <Card>
        <p className="text-sm text-text">The assistant is not available yet.</p>
        <p className="mt-2 text-sm text-text-2">
          It is implemented in the next phase of the project: an LLM that can only call read-only, allowlisted analytics tools
          (no free-form SQL), with authentication, row limits, timeouts and an audit log. This page does not show any
          generated or example answers until that backend exists.
        </p>
      </Card>
    </>
  );
}

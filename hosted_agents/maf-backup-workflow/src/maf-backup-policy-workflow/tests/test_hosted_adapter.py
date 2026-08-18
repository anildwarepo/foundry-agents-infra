import asyncio
import json
import unittest

from backup_api.app import WorkflowSession, _run_workflow_loop
from hosted_agent import _next_interaction


class HostedAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = WorkflowSession()
        self.session.id = "test-session"
        self.session.task = asyncio.create_task(_run_workflow_loop(self.session))

    async def asyncTearDown(self) -> None:
        if self.session.task and not self.session.task.done():
            self.session.task.cancel()
            await asyncio.gather(self.session.task, return_exceptions=True)

    async def test_workflow_advances_between_hitl_screens(self) -> None:
        first = await asyncio.wait_for(
            _next_interaction("test-session", "invocation-1", self.session),
            timeout=10,
        )
        first_screen = first["events"][-1]

        self.assertEqual("awaiting_input", first["status"])
        self.assertEqual("select_source", first_screen["screen"])

        self.session.responses[first_screen["request_id"]] = json.dumps(
            {"platform": "Azure"}
        )
        self.session.response_ready.set()

        second = await asyncio.wait_for(
            _next_interaction("test-session", "invocation-2", self.session),
            timeout=10,
        )
        second_screen = second["events"][-1]

        self.assertEqual("awaiting_input", second["status"])
        self.assertEqual("source_details", second_screen["screen"])


if __name__ == "__main__":
    unittest.main()
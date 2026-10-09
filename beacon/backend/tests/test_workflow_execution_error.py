import pytest

from workflow.models import WorkflowErrorCode, WorkflowExecutionError


def test_workflow_execution_error_preserves_code_and_message():
    error = WorkflowExecutionError(WorkflowErrorCode.PERSISTENCE_FAILED, "Artifact verification failed.")

    assert error.error_code is WorkflowErrorCode.PERSISTENCE_FAILED
    assert str(error) == "Artifact verification failed."

-- The family writer runs the same chain release hook as run-control commands.
-- It may inspect exact named promises/heads and finalized repair subjects, never promote them.
GRANT SELECT ON
    mission_control.output_obligation_head,
    mission_control.output_obligation_revision,
    mission_control.output_revision,
    mission_control.output_accepted_head,
    mission_control.output_submission,
    mission_control.invocation_finalization,
    mission_control.runtime_document
TO mission_control_family_writer;

-- The hook seals one immutable export in its existing admission transaction.
-- Existing scope policy and immutable trigger remain; this role cannot author other detail kinds.
GRANT INSERT ON mission_control.runtime_document TO mission_control_family_writer;
CREATE POLICY runtime_document_family_export_insert
ON mission_control.runtime_document AS RESTRICTIVE FOR INSERT
TO mission_control_family_writer
WITH CHECK (contract = 'linked.export/1');

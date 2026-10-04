import {
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Field,
  Input,
  Textarea,
} from "@fluentui/react-components";
import { useState, type FormEvent } from "react";
import { api, type Project } from "../api/client";
import { ProblemMessage } from "../components/ProblemMessage";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (project: Project) => void;
}

function newKey(): string {
  return `create-${crypto.randomUUID()}`;
}

export function CreateProjectDialog({ open, onOpenChange, onCreated }: Props) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [touched, setTouched] = useState(false);
  // One key per dialog session: retries after a network failure cannot create duplicates.
  const [idempotencyKey, setIdempotencyKey] = useState(newKey);

  const nameError = touched && !name.trim() ? "Enter a project name." : undefined;

  const reset = () => {
    setName("");
    setDescription("");
    setError(null);
    setTouched(false);
    setIdempotencyKey(newKey());
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setTouched(true);
    if (!name.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const project = await api.createProject(
        { name: name.trim(), description: description.trim() || null },
        idempotencyKey,
      );
      reset();
      onCreated(project);
    } catch (err) {
      setError(err);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(_, data) => {
        if (!data.open) reset();
        onOpenChange(data.open);
      }}
    >
      <DialogSurface aria-describedby={undefined}>
        <form onSubmit={submit} noValidate>
          <DialogBody>
            <DialogTitle>New project</DialogTitle>
            <DialogContent>
              <Field label="Name" required validationState={nameError ? "error" : "none"} validationMessage={nameError}>
                <Input
                  value={name}
                  maxLength={200}
                  onChange={(_, data) => setName(data.value)}
                  onBlur={() => setTouched(true)}
                />
              </Field>
              <Field label="Description" hint="What the application should help people do. Optional.">
                <Textarea
                  value={description}
                  maxLength={5000}
                  resize="vertical"
                  onChange={(_, data) => setDescription(data.value)}
                />
              </Field>
              {error !== null && <ProblemMessage error={error} />}
            </DialogContent>
            <DialogActions>
              <Button type="button" appearance="secondary" onClick={() => onOpenChange(false)} disabled={submitting}>
                Cancel
              </Button>
              <Button type="submit" appearance="primary" disabled={submitting}>
                {submitting ? "Creating…" : "Create project"}
              </Button>
            </DialogActions>
          </DialogBody>
        </form>
      </DialogSurface>
    </Dialog>
  );
}

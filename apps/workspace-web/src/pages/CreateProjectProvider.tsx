import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { CreateProjectDialog } from "./CreateProjectDialog";

interface CreateProjectContextValue {
  openCreateProject: () => void;
}

const CreateProjectContext = createContext<CreateProjectContextValue | null>(null);

/**
 * Hosts the create-project dialog above the routes.
 *
 * The dialog must outlive navigation: when it lived inside the projects page, navigating to
 * the new project unmounted it while still open, and Fluent's focus manager left the whole
 * app `aria-hidden` — invisible to screen readers. Found by the Playwright E2E suite in a
 * real browser. Here the dialog closes through its normal path while the route changes.
 */
export function CreateProjectProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const openCreateProject = useCallback(() => setOpen(true), []);
  const value = useMemo(() => ({ openCreateProject }), [openCreateProject]);
  return (
    <CreateProjectContext.Provider value={value}>
      {children}
      <CreateProjectDialog
        open={open}
        onOpenChange={setOpen}
        onCreated={(project) => {
          setOpen(false);
          navigate(`/projects/${project.id}`);
        }}
      />
    </CreateProjectContext.Provider>
  );
}

export function useCreateProject(): CreateProjectContextValue {
  const value = useContext(CreateProjectContext);
  if (!value) throw new Error("useCreateProject must be used inside CreateProjectProvider");
  return value;
}

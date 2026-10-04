import { Link } from "@fluentui/react-components";
import type { MouseEvent, ReactNode } from "react";
import { useNavigate } from "react-router-dom";

/** A Fluent link that navigates client-side but still has a real href (open in new tab, copy link). */
export function RouterLink({ to, children }: { to: string; children: ReactNode }) {
  const navigate = useNavigate();
  const onClick = (event: MouseEvent<HTMLAnchorElement>) => {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
    event.preventDefault();
    navigate(to);
  };
  return (
    <Link href={to} onClick={onClick}>
      {children}
    </Link>
  );
}

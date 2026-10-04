import { Body1, Title2 } from "@fluentui/react-components";
import { RouterLink } from "../components/RouterLink";

export function NotFoundPage() {
  return (
    <>
      <Title2 as="h1">Page not found</Title2>
      <Body1 as="p">
        This page does not exist. <RouterLink to="/projects">Go to projects</RouterLink>
      </Body1>
    </>
  );
}

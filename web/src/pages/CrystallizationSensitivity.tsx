import { Card, PageLink, PageTitle } from "../components/ui";

export function CrystallizationSensitivity() {
  return (
    <>
      <PageTitle pageKey="Crystallization_Sensitivity">Crystallization Sensitivity Protocol</PageTitle>
      <Card title="🚧 Work in Progress">
        <p>
          This page will provide a step-by-step decision tree for assessing the mixing sensitivity of
          crystallization processes, similar to the <PageLink pageKey="Mixing_Sensitivity" />.
        </p>
      </Card>
    </>
  );
}

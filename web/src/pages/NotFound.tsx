import { Link } from "react-router-dom";
import { Card } from "../components/ui";

export function NotFound() {
  return (
    <Card title="Page not found">
      <p>
        This page does not exist in the new app. Go back to the <Link to="/">Home</Link> page.
      </p>
    </Card>
  );
}

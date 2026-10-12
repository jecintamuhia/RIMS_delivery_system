import { Link } from "react-router-dom";
import { EmptyState } from "@/components/ui/EmptyState";
import { Button } from "@/components/ui/Button";
import { MapPinOff } from "lucide-react";
export default function NotFoundPage() {
  return (
    <div className="grid min-h-dvh place-items-center">
      <EmptyState
        icon={MapPinOff}
        title="Page not found"
        description="The page you’re looking for doesn’t exist or has moved."
        action={
          <Link to="/">
            <Button>Back to delivery calculator</Button>
          </Link>
        }
      />
    </div>
  );
}

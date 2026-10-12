import { Mail, Phone } from "lucide-react";
import { usePublicConfig } from "@/features/delivery/hooks";

export function ContactRims() {
  const { data } = usePublicConfig();
  const c = data?.company;
  if (!c?.contactPhone && !c?.contactEmail) return null;
  return (
    <ul className="flex flex-wrap gap-x-5 gap-y-2 text-body">
      {c.contactPhone && (
        <li>
          <a
            className="inline-flex items-center gap-2 font-medium text-brand underline-offset-2 hover:underline"
            href={`tel:${c.contactPhone.replace(/\s/g, "")}`}
          >
            <Phone className="h-4 w-4" aria-hidden />
            {c.contactPhone}
          </a>
        </li>
      )}
      {c.contactEmail && (
        <li>
          <a
            className="inline-flex items-center gap-2 font-medium text-brand underline-offset-2 hover:underline"
            href={`mailto:${c.contactEmail}`}
          >
            <Mail className="h-4 w-4" aria-hidden />
            {c.contactEmail}
          </a>
        </li>
      )}
    </ul>
  );
}

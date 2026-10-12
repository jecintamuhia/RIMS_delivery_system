import { useMemo, useState } from "react";
import { usePublicConfig } from "@/features/delivery/hooks";
import { LOGO_CANDIDATES } from "@/components/intro/assets";
import { cn } from "@/utils/cn";


export function Brand({
  light = false,
  className,
}: {
  light?: boolean;
  className?: string;
}) {
  const { data } = usePublicConfig();
  const name = data?.company.name ?? "RIMs Hardware & Supplies";
  const candidates = useMemo(() => {
    const list = [data?.company.logoUrl, ...LOGO_CANDIDATES].filter(
      Boolean,
    ) as string[];
    return Array.from(new Set(list));
  }, [data?.company.logoUrl]);
  const [index, setIndex] = useState(0);

  const logo = index < candidates.length ? candidates[index] : null;

  return (
    <span className={cn("flex items-center gap-2.5", className)}>
      {logo && (
        <img
          src={logo}
          alt=""
          className="h-7 w-auto"
          decoding="async"
          onError={() => setIndex((i) => i + 1)}
        />
      )}
      <span className={light ? "font-semibold text-white" : "font-semibold"}>
        {name}
      </span>
    </span>
  );
}

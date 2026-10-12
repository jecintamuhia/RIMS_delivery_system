import { z } from "zod";

const optionalNumber = z
  .number({ invalid_type_error: "Enter a number" })
  .nullable();
/** react-hook-form setValueAs helper: empty input becomes null rather than NaN. */
export const numberOrNull = (v: unknown) =>
  v === "" || v === null || v === undefined ? null : Number(v);

export const loginSchema = z.object({
  email: z
    .string()
    .min(1, "Enter your email")
    .email("Enter a valid email address"),
  password: z.string().min(1, "Enter your password"),
});
export type LoginForm = z.infer<typeof loginSchema>;

export const referenceSchema = z.object({
  reference: z
    .string()
    .max(80, "Keep the reference under 80 characters")
    .optional(),
});
export type ReferenceForm = z.infer<typeof referenceSchema>;

export const destinationSchema = z
  .object({
    name: z.string().trim().min(2, "Enter a destination name"),
    code: z
      .string()
      .trim()
      .min(1, "Enter a short code")
      .max(24, "Use 24 characters or fewer"),
    zone: z.string().trim().min(1, "Enter a zone"),
    county: z.string().trim().nullable().optional(),
    lat: optionalNumber.refine(
      (v) => v === null || (v >= -5 && v <= 5.5),
      "Latitude is outside Kenya",
    ),
    lng: optionalNumber.refine(
      (v) => v === null || (v >= 33 && v <= 42.5),
      "Longitude is outside Kenya",
    ),
    active: z.boolean(),
  })
  .refine((v) => (v.lat === null) === (v.lng === null), {
    path: ["lng"],
    message: "Enter both latitude and longitude, or neither",
  });
export type DestinationForm = z.infer<typeof destinationSchema>;

export const roadTypeSchema = z.object({
  name: z.string().trim().min(2, "Enter a road type name"),
  code: z.string().trim().min(1, "Enter a short code").max(24),
  description: z.string().trim().nullable().optional(),
  active: z.boolean(),
});
export type RoadTypeForm = z.infer<typeof roadTypeSchema>;

export const vehicleSchema = z.object({
  name: z.string().trim().min(2, "Enter a vehicle name"),
  code: z.string().trim().min(1, "Enter a short code").max(24),
  maxWeightKg: optionalNumber.refine(
    (v) => v === null || v > 0,
    "Must be greater than 0",
  ),
  maxVolumeM3: optionalNumber.refine(
    (v) => v === null || v > 0,
    "Must be greater than 0",
  ),
  active: z.boolean(),
});
export type VehicleForm = z.infer<typeof vehicleSchema>;

export const pricingRuleSchema = z
  .object({
    destinationId: z.string().min(1, "Choose a destination"),
    roadTypeId: z.string().nullable(),
    vehicleId: z.string().nullable(),
    basePrice: z
      .number({ invalid_type_error: "Enter an amount" })
      .positive("Must be greater than 0"),
    adjustmentType: z.enum(["none", "fixed", "percent"]),
    adjustmentValue: optionalNumber,
    effectiveFrom: z.string().min(1, "Choose an effective date"),
    effectiveTo: z.string().nullable(),
    priority: z
      .number({ invalid_type_error: "Enter a whole number" })
      .int("Enter a whole number"),
    active: z.boolean(),
  })
  .superRefine((v, ctx) => {
    if (v.adjustmentType !== "none" && v.adjustmentValue === null)
      ctx.addIssue({
        code: "custom",
        path: ["adjustmentValue"],
        message: "Enter the adjustment value",
      });
    if (v.effectiveTo && v.effectiveTo < v.effectiveFrom)
      ctx.addIssue({
        code: "custom",
        path: ["effectiveTo"],
        message: "Expiry must be after the effective date",
      });
  });
export type PricingRuleForm = z.infer<typeof pricingRuleSchema>;

export const settingsSchema = z.object({
  dispatchName: z.string().trim().min(2, "Enter the dispatch location name"),
  lat: z.number({ invalid_type_error: "Enter a number" }).min(-5).max(5.5),
  lng: z.number({ invalid_type_error: "Enter a number" }).min(33).max(42.5),
  contactPhone: z.string().trim().nullable(),
  contactEmail: z
    .string()
    .trim()
    .email("Enter a valid email address")
    .or(z.literal(""))
    .nullable(),
});
export type SettingsForm = z.infer<typeof settingsSchema>;

import { lazy, type LazyExoticComponent, type ComponentType } from "react";
import type { ApprovalFormProps } from "./ApprovalFormProps";

type FormComponent = LazyExoticComponent<ComponentType<ApprovalFormProps>>;

const PlaceholderForm = lazy(() => import("./PlaceholderForm"));

/**
 * Map of doc_type.code → form component.
 * PHASE 15~17 will replace PlaceholderForm with concrete forms:
 *   ATT_LEAVE → LeaveRequestForm (PHASE 15)
 *   ATT_FIELD → FieldWorkForm (PHASE 15)
 *   TRAVEL_ORDER → TravelOrderForm (PHASE 16)
 *   CONTRACT_LABOR → LaborContractForm (PHASE 17)
 */
const REGISTRY: Record<string, FormComponent> = {
  ATT_LEAVE: PlaceholderForm,
  ATT_FIELD: PlaceholderForm,
  TRAVEL_ORDER: PlaceholderForm,
  CONTRACT_LABOR: PlaceholderForm,
};

export function resolveForm(docTypeCode: string | null | undefined): FormComponent {
  if (docTypeCode && REGISTRY[docTypeCode]) {
    return REGISTRY[docTypeCode];
  }
  return PlaceholderForm;
}

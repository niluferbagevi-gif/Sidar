import {
  useCallback,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";

export type FormValues = Record<string, unknown>;
export type FormFieldSetter<T extends FormValues> = <K extends keyof T>(
  key: K,
  value: T[K],
) => void;

// Shared controlled-form state helper. Replaces the `setXForm((prev) => ({
// ...prev, [key]: value }))` updater that used to be duplicated per form
// (see OperationsQaPanel.jsx history) with one reusable field setter.
export function useFormState<T extends FormValues>(
  initialValues: T,
): [T, FormFieldSetter<T>, Dispatch<SetStateAction<T>>] {
  const [values, setValues] = useState<T>(initialValues);
  const setField = useCallback<FormFieldSetter<T>>(
    <K extends keyof T>(key: K, value: T[K]) => {
      setValues((prev) => ({ ...prev, [key]: value }));
    },
    [],
  );
  return [values, setField, setValues];
}

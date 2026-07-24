import { useCallback, useState } from "react";

// Shared controlled-form state helper. Replaces the `setXForm((prev) => ({
// ...prev, [key]: value }))` updater that used to be duplicated per form
// (see OperationsQaPanel.jsx history) with one reusable field setter.
export function useFormState(initialValues) {
  const [values, setValues] = useState(initialValues);
  const setField = useCallback((key, value) => {
    setValues((prev) => ({ ...prev, [key]: value }));
  }, []);
  return [values, setField, setValues];
}

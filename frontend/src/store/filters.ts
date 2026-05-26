// frontend/src/store/filters.ts
import { create } from "zustand";
import { ConditionGroup, ConditionLeaf } from "../api/scanner";

export type { ConditionGroup, ConditionLeaf };

function newGroup(logic: "AND" | "OR" = "AND"): ConditionGroup {
  return { id: Math.random().toString(36).slice(2), logic, children: [] };
}

interface FiltersStore {
  source: string;
  defaultTimeframe: string;
  signals: string[];
  customConditions: ConditionGroup | null;
  matchMode: "any_signal" | "all_signals" | "custom_only" | "signals_and_custom";
  maxSymbols: number;
  // actions
  setSource: (s: string) => void;
  setDefaultTimeframe: (tf: string) => void;
  toggleSignal: (name: string) => void;
  setCustomConditions: (tree: ConditionGroup | null) => void;
  setMatchMode: (mode: FiltersStore["matchMode"]) => void;
  setMaxSymbols: (n: number) => void;
  // condition tree manipulation
  addCondition: (groupId: string, leaf: ConditionLeaf) => void;
  removeCondition: (groupId: string, childId: string) => void;
  addGroup: (parentGroupId: string) => void;
  updateCondition: (groupId: string, updatedLeaf: ConditionLeaf) => void;
  updateGroupLogic: (groupId: string, logic: "AND" | "OR") => void;
  initCustomConditions: () => void;
  reset: () => void;
}

function findGroup(node: ConditionGroup, id: string): ConditionGroup | null {
  if (node.id === id) return node;
  for (const child of node.children) {
    if ("logic" in child) {
      const found = findGroup(child as ConditionGroup, id);
      if (found) return found;
    }
  }
  return null;
}

function removeFromGroup(node: ConditionGroup, childId: string): ConditionGroup {
  return {
    ...node,
    children: node.children
      .filter((c) => c.id !== childId)
      .map((c) => ("logic" in c ? removeFromGroup(c as ConditionGroup, childId) : c)),
  };
}

function updateInGroup(node: ConditionGroup, updated: ConditionLeaf): ConditionGroup {
  return {
    ...node,
    children: node.children.map((c) => {
      if (c.id === updated.id) return updated;
      if ("logic" in c) return updateInGroup(c as ConditionGroup, updated);
      return c;
    }),
  };
}

function updateGroupLogicInTree(node: ConditionGroup, groupId: string, logic: "AND" | "OR"): ConditionGroup {
  if (node.id === groupId) return { ...node, logic };
  return {
    ...node,
    children: node.children.map((c) =>
      "logic" in c ? updateGroupLogicInTree(c as ConditionGroup, groupId, logic) : c
    ),
  };
}

export const useFiltersStore = create<FiltersStore>((set, get) => ({
  source: "nse_all",
  defaultTimeframe: "1d",
  signals: [],
  customConditions: null,
  matchMode: "any_signal",
  maxSymbols: 500,

  setSource: (source) => set({ source }),
  setDefaultTimeframe: (tf) => set({ defaultTimeframe: tf }),
  toggleSignal: (name) =>
    set((s) => ({
      signals: s.signals.includes(name) ? s.signals.filter((n) => n !== name) : [...s.signals, name],
    })),
  setCustomConditions: (tree) => set({ customConditions: tree }),
  setMatchMode: (mode) => set({ matchMode: mode }),
  setMaxSymbols: (n) => set({ maxSymbols: n }),

  initCustomConditions: () => {
    if (!get().customConditions) {
      set({ customConditions: newGroup("AND") });
    }
  },

  addCondition: (groupId, leaf) =>
    set((s) => {
      if (!s.customConditions) return s;
      const root = { ...s.customConditions };
      const group = findGroup(root, groupId);
      if (!group) return s;
      group.children = [...group.children, leaf];
      return { customConditions: root };
    }),

  removeCondition: (_groupId, childId) =>
    set((s) => {
      if (!s.customConditions) return s;
      return { customConditions: removeFromGroup(s.customConditions, childId) };
    }),

  addGroup: (parentGroupId) =>
    set((s) => {
      if (!s.customConditions) return s;
      const root = { ...s.customConditions };
      const parent = findGroup(root, parentGroupId);
      if (!parent) return s;
      parent.children = [...parent.children, newGroup("AND")];
      return { customConditions: root };
    }),

  updateCondition: (_groupId, updatedLeaf) =>
    set((s) => {
      if (!s.customConditions) return s;
      return { customConditions: updateInGroup(s.customConditions, updatedLeaf) };
    }),

  updateGroupLogic: (groupId, logic) =>
    set((s) => {
      if (!s.customConditions) return s;
      return { customConditions: updateGroupLogicInTree(s.customConditions, groupId, logic) };
    }),

  reset: () =>
    set({
      source: "nse_all",
      defaultTimeframe: "1d",
      signals: [],
      customConditions: null,
      matchMode: "any_signal",
      maxSymbols: 500,
    }),
}));

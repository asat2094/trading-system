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

function addToGroup(node: ConditionGroup, groupId: string, leaf: ConditionLeaf): ConditionGroup {
  if (node.id === groupId) {
    return { ...node, children: [...node.children, leaf] };
  }
  return {
    ...node,
    children: node.children.map((c) =>
      "logic" in c ? addToGroup(c as ConditionGroup, groupId, leaf) : c
    ),
  };
}

function addGroupToParent(node: ConditionGroup, parentId: string, newGroup: ConditionGroup): ConditionGroup {
  if (node.id === parentId) {
    return { ...node, children: [...node.children, newGroup] };
  }
  return {
    ...node,
    children: node.children.map((c) =>
      "logic" in c ? addGroupToParent(c as ConditionGroup, parentId, newGroup) : c
    ),
  };
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
      return { customConditions: addToGroup(s.customConditions, groupId, leaf) };
    }),

  removeCondition: (_groupId, childId) =>
    set((s) => {
      if (!s.customConditions) return s;
      return { customConditions: removeFromGroup(s.customConditions, childId) };
    }),

  addGroup: (parentGroupId) =>
    set((s) => {
      if (!s.customConditions) return s;
      return { customConditions: addGroupToParent(s.customConditions, parentGroupId, newGroup("AND")) };
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

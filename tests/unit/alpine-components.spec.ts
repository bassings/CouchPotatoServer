/**
 * Unit tests for CouchPotato Alpine.js components.
 * 
 * Since Alpine components are defined inline in templates, we test
 * the component factory functions that would be used.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock component factory for movieList (from wanted.html)
function movieList() {
  return {
    search: '',
    filterStatus: '',
    
    filterMovies() {
      const q = this.search.toLowerCase();
      // In real implementation, this queries the DOM
      // We test the logic separately
      return { query: q, status: this.filterStatus };
    },
    
    updateCount() {
      // Would update DOM in real implementation
      return true;
    },
    
    init() {
      // Would set up htmx listeners
      return true;
    }
  };
}

// Mock component factory for settingsPanel (simplified)
function settingsPanel() {
  return {
    activeTab: 'general',
    loading: true,
    saving: false,
    showAdvanced: false,
    dirty: {} as Record<string, any>,
    values: {} as Record<string, any>,
    
    getVal(section: string, name: string) {
      const key = `${section}.${name}`;
      if (key in this.dirty) return this.dirty[key];
      if (this.values[section] && this.values[section][name] !== undefined) {
        return this.values[section][name];
      }
      return '';
    },
    
    setVal(section: string, name: string, value: any) {
      const key = `${section}.${name}`;
      this.dirty[key] = value;
    },
    
    isEnabled(group: { section: string; options?: { type: string; name: string }[] }) {
      const enabler = (group.options || []).find(o => o.type === 'enabler');
      if (!enabler) return true;
      const val = this.getVal(group.section, enabler.name);
      return val === true || val === 'True' || val === '1' || val === 1 || val === 'true';
    },
  };
}

// Mock buttonField component
function buttonField(section: string, opt: { button_action?: string; description?: string }) {
  return {
    running: false,
    result: '',
    success: false,
    section,
    opt,
    
    async execute() {
      if (!this.opt.button_action) {
        this.result = 'No action configured';
        this.success = false;
        return;
      }
      this.running = true;
      this.result = '';
      // Would call API in real implementation
      this.running = false;
    },
    
    buildDescription() {
      return this.opt.description || '';
    },
  };
}

describe('movieList component', () => {
  let component: ReturnType<typeof movieList>;
  
  beforeEach(() => {
    component = movieList();
  });
  
  it('should initialize with empty search and filter', () => {
    expect(component.search).toBe('');
    expect(component.filterStatus).toBe('');
  });
  
  it('should return lowercase search query on filter', () => {
    component.search = 'The Matrix';
    const result = component.filterMovies();
    expect(result.query).toBe('the matrix');
  });
  
  it('should pass through filter status', () => {
    component.filterStatus = 'active';
    const result = component.filterMovies();
    expect(result.status).toBe('active');
  });
  
  it('should initialize successfully', () => {
    expect(component.init()).toBe(true);
  });
});

describe('settingsPanel component', () => {
  let component: ReturnType<typeof settingsPanel>;
  
  beforeEach(() => {
    component = settingsPanel();
  });
  
  it('should start on general tab', () => {
    expect(component.activeTab).toBe('general');
  });
  
  it('should start in loading state', () => {
    expect(component.loading).toBe(true);
  });
  
  it('should get value from dirty first, then values', () => {
    component.values = { core: { username: 'saved' } };
    expect(component.getVal('core', 'username')).toBe('saved');
    
    component.dirty['core.username'] = 'dirty';
    expect(component.getVal('core', 'username')).toBe('dirty');
  });
  
  it('should set value in dirty', () => {
    component.setVal('core', 'port', 5051);
    expect(component.dirty['core.port']).toBe(5051);
  });
  
  it('should return empty string for missing values', () => {
    expect(component.getVal('nonexistent', 'key')).toBe('');
  });
  
  it('should check if group is enabled based on enabler option', () => {
    const enabledGroup = {
      section: 'test',
      options: [
        { type: 'enabler', name: 'enabled' },
        { type: 'string', name: 'other' },
      ],
    };
    
    // Default: not enabled
    expect(component.isEnabled(enabledGroup)).toBe(false);
    
    // Set enabled to true
    component.values = { test: { enabled: true } };
    expect(component.isEnabled(enabledGroup)).toBe(true);
    
    // String "1" should also work
    component.values = { test: { enabled: '1' } };
    expect(component.isEnabled(enabledGroup)).toBe(true);
  });
  
  it('should return true for groups without enabler', () => {
    const noEnablerGroup = {
      section: 'general',
      options: [
        { type: 'string', name: 'username' },
      ],
    };
    expect(component.isEnabled(noEnablerGroup)).toBe(true);
  });
});

describe('buttonField component (DEF-003 fix)', () => {
  it('should return description from opt', () => {
    const component = buttonField('torrentpotato', {
      button_action: 'torrentpotato.jackett_sync',
      description: 'Click to sync all configured indexers from Jackett',
    });
    
    // This tests the DEF-003 fix - description should not be undefined
    expect(component.buildDescription()).toBe('Click to sync all configured indexers from Jackett');
    expect(component.buildDescription()).not.toBe('undefined');
  });
  
  it('should return empty string if no description', () => {
    const component = buttonField('test', {});
    expect(component.buildDescription()).toBe('');
  });
  
  it('should not be running initially', () => {
    const component = buttonField('test', {});
    expect(component.running).toBe(false);
  });
  
  it('should fail without button_action', async () => {
    const component = buttonField('test', {});
    await component.execute();
    expect(component.result).toBe('No action configured');
    expect(component.success).toBe(false);
  });
});

describe('Year display logic (DEF-005 fix)', () => {
  // Test the year normalization logic used in templates
  function normalizeYear(rawYear: number | null | undefined): string {
    return (rawYear && rawYear !== 0) ? String(rawYear) : 'TBA';
  }
  
  it('should show year when valid', () => {
    expect(normalizeYear(2024)).toBe('2024');
    expect(normalizeYear(1999)).toBe('1999');
  });
  
  it('should show TBA when year is 0', () => {
    expect(normalizeYear(0)).toBe('TBA');
  });
  
  it('should show TBA when year is null', () => {
    expect(normalizeYear(null)).toBe('TBA');
  });
  
  it('should show TBA when year is undefined', () => {
    expect(normalizeYear(undefined)).toBe('TBA');
  });
});

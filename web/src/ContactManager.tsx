import { ChangeEvent, FormEvent, useEffect, useMemo, useState } from 'react';
import { Spinner } from './Spinner';

export type Contact = {
  id: string;
  displayName: string;
  givenName: string;
  familyName: string;
  company: string;
  jobTitle: string;
  emails: string[];
  phones: string[];
  addresses: string[];
  notes: string;
  birthday: string | null;
  openChatUsername: string;
  openChatFriendCode: string;
  groupIds: string[];
  createdAt: string;
  updatedAt: string;
};

type ContactGroup = { id: string; name: string; color: string; contact_count: number };
type ContactManagerData = { appVersion: string; openChatUrl: string | null };
type EditorValue = Omit<Contact, 'id' | 'createdAt' | 'updatedAt'>;

const emptyContact: EditorValue = {
  displayName: '', givenName: '', familyName: '', company: '', jobTitle: '', emails: [], phones: [],
  addresses: [], notes: '', birthday: null, openChatUsername: '', openChatFriendCode: '', groupIds: [],
};

const initials = (name: string) => name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase()).join('') || '?';
const lines = (value: string) => value.split('\n').map((part) => part.trim()).filter(Boolean);
const openChatHref = (base: string, contact: Contact) => {
  const url = new URL(base, window.location.href);
  if (contact.openChatFriendCode) url.searchParams.set('friendCode', contact.openChatFriendCode);
  else if (contact.openChatUsername) url.searchParams.set('username', contact.openChatUsername);
  return url.toString();
};

function ContactEditor({ contact, groups, onClose, onSaved }: {
  contact: Contact | null;
  groups: ContactGroup[];
  onClose: () => void;
  onSaved: (contact: Contact) => void;
}) {
  const [value, setValue] = useState<EditorValue>(() => contact ? {
    displayName: contact.displayName, givenName: contact.givenName, familyName: contact.familyName,
    company: contact.company, jobTitle: contact.jobTitle, emails: contact.emails, phones: contact.phones,
    addresses: contact.addresses, notes: contact.notes, birthday: contact.birthday,
    openChatUsername: contact.openChatUsername, openChatFriendCode: contact.openChatFriendCode,
    groupIds: contact.groupIds,
  } : emptyContact);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setSaving(true); setError('');
    try {
      const response = await fetch(contact ? `/api/contacts/${encodeURIComponent(contact.id)}` : '/api/contacts', {
        method: contact ? 'PUT' : 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(value),
      });
      const result = await response.json().catch(() => ({})) as Contact & { detail?: string };
      if (!response.ok) throw new Error(result.detail || `Could not save contact (${response.status})`);
      onSaved(result);
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); setSaving(false); }
  };
  return <div className="os-layer" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="os-dialog os-contact-editor" role="dialog" aria-modal="true" aria-label={contact ? `Edit ${contact.displayName}` : 'New contact'}>
      <header className="os-dialog-header"><div><span className="eyebrow">Contact manager</span><h2>{contact ? 'Edit contact' : 'New contact'}</h2><p>Keep personal details private to your OpenShare account.</p></div><button className="os-icon-button" type="button" aria-label="Close" onClick={onClose}>×</button></header>
      <form className="os-contact-form" onSubmit={submit}>
        <div className="os-contact-form-grid">
          <label className="os-field os-contact-wide"><span>Display name</span><input autoFocus required value={value.displayName} onChange={(event) => setValue({ ...value, displayName: event.target.value })} /></label>
          <label className="os-field"><span>First name</span><input value={value.givenName} onChange={(event) => setValue({ ...value, givenName: event.target.value })} /></label>
          <label className="os-field"><span>Last name</span><input value={value.familyName} onChange={(event) => setValue({ ...value, familyName: event.target.value })} /></label>
          <label className="os-field"><span>Company</span><input value={value.company} onChange={(event) => setValue({ ...value, company: event.target.value })} /></label>
          <label className="os-field"><span>Role</span><input value={value.jobTitle} onChange={(event) => setValue({ ...value, jobTitle: event.target.value })} /></label>
          <label className="os-field"><span>Email addresses</span><textarea rows={3} value={value.emails.join('\n')} onChange={(event) => setValue({ ...value, emails: lines(event.target.value) })} placeholder="One per line" /></label>
          <label className="os-field"><span>Phone numbers</span><textarea rows={3} value={value.phones.join('\n')} onChange={(event) => setValue({ ...value, phones: lines(event.target.value) })} placeholder="One per line" /></label>
          <label className="os-field os-contact-wide"><span>Addresses</span><textarea rows={3} value={value.addresses.join('\n')} onChange={(event) => setValue({ ...value, addresses: lines(event.target.value) })} placeholder="One per line" /></label>
          <label className="os-field"><span>Birthday</span><input type="date" value={value.birthday?.startsWith('--') ? '' : value.birthday ?? ''} onChange={(event) => setValue({ ...value, birthday: event.target.value || null })} /></label>
          <span />
          <fieldset className="os-contact-integration os-contact-wide"><legend>OpenChat</legend><p>Link this address-book entry to an OpenChat identity without sharing the rest of the contact.</p><div>
            <label className="os-field"><span>Username</span><input value={value.openChatUsername} onChange={(event) => setValue({ ...value, openChatUsername: event.target.value })} placeholder="username" /></label>
            <label className="os-field"><span>Friend code</span><input inputMode="numeric" pattern="[0-9]{8}" maxLength={8} value={value.openChatFriendCode} onChange={(event) => setValue({ ...value, openChatFriendCode: event.target.value.replace(/\D/g, '').slice(0, 8) })} placeholder="8 digits" /></label>
          </div></fieldset>
          {groups.length > 0 && <fieldset className="os-contact-groups-field os-contact-wide"><legend>Groups</legend><div>{groups.map((group) => <label key={group.id} style={{ '--group-color': group.color } as React.CSSProperties}><input type="checkbox" checked={value.groupIds.includes(group.id)} onChange={(event) => setValue({ ...value, groupIds: event.target.checked ? [...value.groupIds, group.id] : value.groupIds.filter((id) => id !== group.id) })} /><span>{group.name}</span></label>)}</div></fieldset>}
          <label className="os-field os-contact-wide"><span>Notes</span><textarea rows={5} value={value.notes} onChange={(event) => setValue({ ...value, notes: event.target.value })} /></label>
        </div>
        {error && <div className="os-form-error" role="alert">{error}</div>}
        <footer className="os-dialog-actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={saving}>{saving && <Spinner size="xs" label="Saving contact" />} Save contact</button></footer>
      </form>
    </section>
  </div>;
}

export function ContactManager({ data }: { data: ContactManagerData }) {
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [groups, setGroups] = useState<ContactGroup[]>([]);
  const [query, setQuery] = useState('');
  const [groupId, setGroupId] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editing, setEditing] = useState<Contact | null | undefined>(undefined);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [groupName, setGroupName] = useState('');
  const [groupColor, setGroupColor] = useState('#3298ff');
  const [importing, setImporting] = useState(false);
  const selected = useMemo(() => contacts.find((contact) => contact.id === selectedId) ?? contacts[0] ?? null, [contacts, selectedId]);

  useEffect(() => {
    fetch('/api/contact-groups', { credentials: 'same-origin' }).then((response) => response.json()).then((body) => setGroups(body.groups ?? [])).catch(() => setError('Could not load contact groups'));
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setLoading(true);
      const params = new URLSearchParams(); if (query.trim()) params.set('q', query.trim()); if (groupId) params.set('group_id', groupId);
      fetch(`/api/contacts?${params}`, { credentials: 'same-origin', signal: controller.signal })
        .then(async (response) => { if (!response.ok) throw new Error(`Could not load contacts (${response.status})`); return response.json(); })
        .then((body) => { setContacts(body.contacts ?? []); setLoading(false); })
        .catch((reason) => { if (reason.name !== 'AbortError') { setError(reason.message); setLoading(false); } });
    }, 150);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [query, groupId]);

  const remove = async (contact: Contact) => {
    if (!window.confirm(`Delete ${contact.displayName}?`)) return;
    const response = await fetch(`/api/contacts/${encodeURIComponent(contact.id)}`, { method: 'DELETE', credentials: 'same-origin' });
    if (response.ok) { setContacts((before) => before.filter((item) => item.id !== contact.id)); setSelectedId(null); }
    else setError(`Could not delete contact (${response.status})`);
  };
  const addGroup = async (event: FormEvent) => {
    event.preventDefault(); if (!groupName.trim()) return;
    const response = await fetch('/api/contact-groups', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: groupName.trim(), color: groupColor }) });
    const result = await response.json().catch(() => ({}));
    if (response.ok) { setGroups((before) => [...before, result]); setGroupName(''); }
    else setError(result.detail || `Could not add group (${response.status})`);
  };
  const deleteGroup = async (group: ContactGroup) => {
    if (!window.confirm(`Delete the ${group.name} group? Contacts will be kept.`)) return;
    const response = await fetch(`/api/contact-groups/${encodeURIComponent(group.id)}`, { method: 'DELETE', credentials: 'same-origin' });
    if (response.ok) {
      setGroups((before) => before.filter((candidate) => candidate.id !== group.id));
      setContacts((before) => before.map((contact) => ({ ...contact, groupIds: contact.groupIds.filter((id) => id !== group.id) })));
      if (groupId === group.id) setGroupId('');
    } else setError(`Could not delete group (${response.status})`);
  };
  const importFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]; if (!file) return;
    setImporting(true); setError(''); const body = new FormData(); body.append('file', file);
    try {
      const response = await fetch('/api/contacts/import', { method: 'POST', credentials: 'same-origin', body });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.detail || `Import failed (${response.status})`);
      setContacts((before) => [...(result.contacts ?? []), ...before]);
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setImporting(false); event.target.value = ''; }
  };

  return <section className="os-contact-shell">
    <header className="os-contact-hero"><div><span className="eyebrow">Personal information</span><h1>Contacts</h1><p>A private, portable address book with optional OpenChat identity links.</p></div><div className="os-contact-hero-actions"><label className="btn"><input type="file" hidden accept=".vcf,.vcard,.csv,text/vcard,text/csv" onChange={importFile} disabled={importing} />{importing ? <><Spinner size="xs" label="Importing contacts" /> Importing…</> : 'Import'}</label><a className="btn" href="/api/contacts/export.vcf">Export vCard</a><button className="btn primary" type="button" onClick={() => setEditing(null)}>New contact</button></div></header>
    {error && <div className="os-form-error" role="alert">{error}<button type="button" aria-label="Dismiss" onClick={() => setError('')}>×</button></div>}
    <div className="os-contact-toolbar"><label className="os-contact-search"><span aria-hidden="true">⌕</span><input type="search" placeholder="Search names, companies, notes, email, phone, or OpenChat…" value={query} onChange={(event) => setQuery(event.target.value)} /></label><form onSubmit={addGroup}><input className="os-contact-group-color" type="color" value={groupColor} onChange={(event) => setGroupColor(event.target.value)} aria-label="New group color" /><input value={groupName} onChange={(event) => setGroupName(event.target.value)} placeholder="New group" aria-label="New group name" /><button type="submit">Add group</button></form></div>
    <nav className="os-contact-filters" aria-label="Contact groups"><button className={!groupId ? 'is-active' : ''} type="button" onClick={() => setGroupId('')}>All <span>{contacts.length}</span></button>{groups.map((group) => <span className="os-contact-group-chip" key={group.id} style={{ '--group-color': group.color } as React.CSSProperties}><button className={groupId === group.id ? 'is-active' : ''} type="button" onClick={() => setGroupId(group.id)}>{group.name} <span>{group.contact_count}</span></button><button className="os-contact-group-remove" type="button" aria-label={`Delete ${group.name} group`} onClick={() => void deleteGroup(group)}>×</button></span>)}</nav>
    <div className="os-contact-workspace">
      <aside className="os-contact-list" aria-label="Contacts">
        {loading && <div className="os-contact-empty"><Spinner label="Loading contacts" /> Loading contacts…</div>}
        {!loading && contacts.length === 0 && <div className="os-contact-empty"><strong>No contacts found</strong><span>{query || groupId ? 'Try another search or group.' : 'Create a contact or import vCard/CSV.'}</span></div>}
        {!loading && contacts.map((contact) => <button key={contact.id} className={selected?.id === contact.id ? 'is-selected' : ''} type="button" onClick={() => setSelectedId(contact.id)}><span className="os-contact-avatar">{initials(contact.displayName)}</span><span><strong>{contact.displayName}</strong><small>{[contact.jobTitle, contact.company].filter(Boolean).join(' · ') || contact.emails[0] || contact.phones[0] || 'Contact'}</small></span>{contact.openChatFriendCode && <span className="os-openchat-dot" title="Linked to OpenChat" aria-label="Linked to OpenChat" />}</button>)}
      </aside>
      <article className="os-contact-detail">
        {!selected ? <div className="os-contact-empty"><strong>Select a contact</strong><span>Details and actions appear here.</span></div> : <>
          <header><span className="os-contact-avatar is-large">{initials(selected.displayName)}</span><div><span className="eyebrow">Contact</span><h2>{selected.displayName}</h2><p>{[selected.jobTitle, selected.company].filter(Boolean).join(' at ') || 'Personal contact'}</p></div><div><button type="button" onClick={() => setEditing(selected)}>Edit</button><button className="danger" type="button" onClick={() => void remove(selected)}>Delete</button></div></header>
          <div className="os-contact-detail-grid">
            {selected.emails.length > 0 && <section><h3>Email</h3>{selected.emails.map((email) => <a href={`mailto:${email}`} key={email}>{email}</a>)}</section>}
            {selected.phones.length > 0 && <section><h3>Phone</h3>{selected.phones.map((phone) => <a href={`tel:${phone}`} key={phone}>{phone}</a>)}</section>}
            {selected.addresses.length > 0 && <section><h3>Address</h3>{selected.addresses.map((address) => <p key={address}>{address}</p>)}</section>}
            {selected.birthday && <section><h3>Birthday</h3><p>{selected.birthday}</p></section>}
            {(selected.openChatUsername || selected.openChatFriendCode) && <section className="os-openchat-card"><h3>OpenChat</h3>{selected.openChatUsername && <p>@{selected.openChatUsername}</p>}{selected.openChatFriendCode && <code>{selected.openChatFriendCode}</code>}<div>{selected.openChatFriendCode && <button type="button" onClick={() => navigator.clipboard.writeText(selected.openChatFriendCode)}>Copy friend code</button>}{data.openChatUrl && <a href={openChatHref(data.openChatUrl, selected)} target="_blank" rel="noopener">Open OpenChat</a>}</div></section>}
            {selected.notes && <section className="os-contact-notes"><h3>Notes</h3><p>{selected.notes}</p></section>}
          </div>
        </>}
      </article>
    </div>
    <footer className="os-contact-footer">OpenShare v{data.appVersion}</footer>
    {editing !== undefined && <ContactEditor contact={editing} groups={groups} onClose={() => setEditing(undefined)} onSaved={(saved) => { setContacts((before) => [saved, ...before.filter((contact) => contact.id !== saved.id)]); setSelectedId(saved.id); setEditing(undefined); }} />}
  </section>;
}

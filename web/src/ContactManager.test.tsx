import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ContactManager } from './ContactManager';

const contact = {
  id: 'contact-1', displayName: 'Ada Lovelace', givenName: 'Ada', familyName: 'Lovelace',
  company: 'Analytical Engines', jobTitle: 'Mathematician', emails: ['ada@example.test'],
  phones: ['+1 555 0100'], addresses: ['12 Computing Lane'], notes: 'Writes algorithms',
  birthday: '1815-12-10', openChatUsername: 'ada', openChatFriendCode: '12345678',
  groupIds: ['group-1'], createdAt: '2026-08-09', updatedAt: '2026-08-09',
};

describe('ContactManager', () => {
  it('searches private contacts and exposes explicit OpenChat actions', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input);
      if (url === '/api/contact-groups') return new Response(JSON.stringify({ groups: [{ id: 'group-1', name: 'Research', color: '#18d5ad', contact_count: 1 }] }), { status: 200 });
      if (url.startsWith('/api/contacts?')) return new Response(JSON.stringify({ contacts: [contact] }), { status: 200 });
      throw new Error(`Unexpected request ${url}`);
    });

    render(<ContactManager data={{ appVersion: '0.2.35', openChatUrl: 'https://chat.example.test' }} />);
    expect(await screen.findByRole('heading', { name: 'Ada Lovelace' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open OpenChat' })).toHaveAttribute('href', 'https://chat.example.test/?friendCode=12345678');

    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'engine' } });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/contacts?q=engine', expect.objectContaining({ credentials: 'same-origin' })));
  });

  it('opens the contact editor with OpenChat friend-code validation controls', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      if (String(input) === '/api/contact-groups') return new Response(JSON.stringify({ groups: [] }), { status: 200 });
      return new Response(JSON.stringify({ contacts: [] }), { status: 200 });
    });
    render(<ContactManager data={{ appVersion: '0.2.35', openChatUrl: null }} />);
    fireEvent.click(screen.getByRole('button', { name: 'New contact' }));
    expect(screen.getByRole('dialog', { name: 'New contact' })).toBeInTheDocument();
    expect(screen.getByLabelText('Friend code')).toHaveAttribute('pattern', '[0-9]{8}');
  });
});

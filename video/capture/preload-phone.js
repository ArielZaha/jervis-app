// For filming the phone app (phone_client.html): the hand-driven clock, and the page believes it is the installed
// Home Screen app (as on a real phone after "Add to Home Screen").
require('./clock.js');
Object.defineProperty(Navigator.prototype, 'standalone', { get: () => true });

var TraktAutomation = new Class({

	pollTimer: null,
	pollInterval: 5000,

	initialize: function(){
		var self = this;
		App.addEvent('loadSettings', self.addRegisterButton.bind(self));
	},

	addRegisterButton: function(){
		var self = this,
			setting_page = App.getPage('Settings');

		setting_page.addEvent('create', function(){

			var fieldset = setting_page.tabs.automation.groups.trakt_automation;
			if (!fieldset) return;

			// Check if already authorized
			var token_input = fieldset.getElement('input[name*=oauth_token]');
			var is_authorized = token_input && token_input.get('value') !== '';

			// Create the auth controls container
			var auth_container = new Element('div.ctrlHolder.trakt-auth-container');

			if (is_authorized) {
				// Show "Connected" status and unregister button
				auth_container.adopt(
					new Element('span.trakt-status.connected', {
						'html': '<span class="icon-ok"></span> Connected to Trakt'
					}),
					new Element('a.button.red', {
						'text': 'Disconnect',
						'events': {
							'click': function(){
								fieldset.getElement('input[name*=oauth_token]').set('value', '').fireEvent('change');
								fieldset.getElement('input[name*=oauth_refresh]').set('value', '').fireEvent('change');
								// Reload the settings page to refresh UI
								window.location.reload();
							}
						}
					})
				);
			} else {
				// Show authorization button
				auth_container.adopt(
					new Element('a.button.green', {
						'text': 'Authorize with Trakt',
						'events': {
							'click': self.startDeviceAuth.bind(self)
						}
					}),
					new Element('p.formHint', {
						'html': 'First, enter your Client ID and Client Secret above. ' +
							'<a href="https://trakt.tv/oauth/applications" target="_blank">Create a Trakt app</a> if you don\'t have one.'
					})
				);
			}

			// Add status/code display area
			self.statusArea = new Element('div.trakt-auth-status');
			auth_container.adopt(self.statusArea);

			auth_container.inject(fieldset);

			// Add some CSS
			self.addStyles();
		});
	},

	addStyles: function(){
		if (document.id('trakt-auth-styles')) return;

		var css = '\
			.trakt-auth-container { margin-top: 15px; padding: 15px; background: rgba(0,0,0,0.1); border-radius: 4px; } \
			.trakt-auth-container .button { margin-right: 10px; } \
			.trakt-auth-container .formHint { margin-top: 10px; font-size: 11px; opacity: 0.7; } \
			.trakt-status.connected { color: #5cb85c; margin-right: 15px; font-weight: bold; } \
			.trakt-status .icon-ok { margin-right: 5px; } \
			.trakt-auth-status { margin-top: 15px; } \
			.trakt-device-code { \
				background: #2d2d2d; \
				padding: 20px; \
				border-radius: 4px; \
				text-align: center; \
				margin-top: 15px; \
			} \
			.trakt-device-code h3 { margin: 0 0 15px 0; font-size: 16px; } \
			.trakt-device-code .code { \
				font-size: 32px; \
				font-family: monospace; \
				font-weight: bold; \
				letter-spacing: 5px; \
				color: #ed1c24; \
				padding: 15px; \
				background: #1a1a1a; \
				border-radius: 4px; \
				display: inline-block; \
				margin: 10px 0; \
			} \
			.trakt-device-code .url { \
				font-size: 18px; \
				margin: 10px 0; \
			} \
			.trakt-device-code .url a { color: #4fc3f7; } \
			.trakt-device-code .status { \
				margin-top: 15px; \
				font-size: 13px; \
				opacity: 0.7; \
			} \
			.trakt-device-code .status.polling { \
				opacity: 1; \
				color: #ffc107; \
			} \
			.trakt-device-code .status.success { \
				color: #5cb85c; \
				font-weight: bold; \
			} \
			.trakt-device-code .status.error { \
				color: #d9534f; \
			} \
		';

		new Element('style', {
			'id': 'trakt-auth-styles',
			'type': 'text/css',
			'html': css
		}).inject(document.head);
	},

	startDeviceAuth: function(){
		var self = this;

		self.statusArea.empty();
		self.statusArea.adopt(new Element('p', {'text': 'Starting authorization...'}));

		Api.request('automation.trakt.device_code', {
			'onComplete': function(json){
				if (json.success) {
					self.showDeviceCode(json);
				} else {
					self.showError(json.error || 'Failed to start authorization');
				}
			}
		});
	},

	showDeviceCode: function(data){
		var self = this;

		self.statusArea.empty();

		var codeBox = new Element('div.trakt-device-code');
		codeBox.adopt(
			new Element('h3', {'text': 'Authorize CouchPotato on Trakt'}),
			new Element('p.url', {
				'html': 'Visit: <a href="' + data.verification_url + '" target="_blank">' + data.verification_url + '</a>'
			}),
			new Element('p', {'text': 'Enter this code:'}),
			new Element('div.code', {'text': data.user_code}),
			self.pollStatus = new Element('p.status.polling', {'text': 'Waiting for authorization...'})
		);

		self.statusArea.adopt(codeBox);

		// Start polling
		self.pollInterval = (data.interval || 5) * 1000;
		self.pollForToken();
	},

	pollForToken: function(){
		var self = this;

		// Clear any existing timer
		if (self.pollTimer) {
			clearTimeout(self.pollTimer);
		}

		Api.request('automation.trakt.poll_token', {
			'onComplete': function(json){
				if (json.success) {
					// Authorization successful!
					self.showSuccess();
				} else if (json.pending) {
					// Still waiting, poll again
					if (json.slow_down) {
						self.pollInterval = Math.min(self.pollInterval * 2, 30000);
					}
					self.pollTimer = setTimeout(self.pollForToken.bind(self), self.pollInterval);
				} else if (json.expired) {
					// Code expired
					self.showError('Authorization code expired. Please try again.');
				} else {
					// Error
					self.showError(json.error || 'Authorization failed');
				}
			}
		});
	},

	showSuccess: function(){
		var self = this;

		if (self.pollTimer) {
			clearTimeout(self.pollTimer);
		}

		if (self.pollStatus) {
			self.pollStatus.set('class', 'status success');
			self.pollStatus.set('text', '✓ Authorization successful! Refreshing page...');
		}

		// Reload the page to show the new connected state
		setTimeout(function(){
			window.location.reload();
		}, 1500);
	},

	showError: function(message){
		var self = this;

		if (self.pollTimer) {
			clearTimeout(self.pollTimer);
		}

		self.statusArea.empty();
		self.statusArea.adopt(
			new Element('p.status.error', {'text': message}),
			new Element('a.button', {
				'text': 'Try Again',
				'events': {
					'click': self.startDeviceAuth.bind(self)
				}
			})
		);
	}

});

new TraktAutomation();

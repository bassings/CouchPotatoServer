var AboutSettingTab = new Class({

	tab: '',
	content: '',

	initialize: function(){
		var self = this;

		App.addEvent('loadSettings', self.addSettings.bind(self));

	},

	addSettings: function(){
		var self = this;

		self.settings = App.getPage('Settings');
		self.settings.addEvent('create', function(){
			var tab = self.settings.createTab('about', {
				'label': 'About',
				'name': 'about'
			});

			self.tab = tab.tab;
			self.content = tab.content;

			self.createAbout();

		});

		self.settings.default_action = 'about';
		// WebUI Feature:
		self.hide_about_dirs = !! App.options && App.options.webui_feature && App.options.webui_feature.hide_about_dirs;
		self.hide_about_update = !! App.options && App.options.webui_feature && App.options.webui_feature.hide_about_update;
	},

	createAbout: function(){
		var self = this;

		var about_block;
		self.settings.createGroup({
			'label': 'About This CouchPotato',
			'name': 'variables'
		}).inject(self.content).adopt(
			(about_block = new Element('dl.info')).adopt(
				new Element('dt[text=Version]'),
				self.version_text = new Element('dd.version', {
					'text': 'Getting version...'
				}),

				new Element('dt[text=Updater]'),
				self.updater_type = new Element('dd.updater'),
				new Element('dt[text=ID]'),
				new Element('dd', {'text': App.getOption('pid')})
			)
		);

		if (!self.hide_about_update){
			self.version_text.addEvents({		
				'click': App.checkForUpdate.bind(App, function(json){
					self.fillVersion(json.info);
				}),			
				'mouseenter': function(){
					this.set('text', 'Check for updates');
				},
				'mouseleave': function(){
					self.fillVersion(Updater.getInfo());
				}
			});
		} else {
			// override cursor style from CSS
			self.version_text.setProperty('style', 'cursor: auto');
		}

		if (!self.hide_about_dirs){
			about_block.adopt(
				new Element('dt[text=Directories]'),
				new Element('dd', {'text': App.getOption('app_dir')}),
				new Element('dd', {'text': App.getOption('data_dir')}),
				new Element('dt[text=Startup Args]'),
				new Element('dd', {'html': App.getOption('args')}),
				new Element('dd', {'html': App.getOption('options')})
			);
		}

		if(!self.fillVersion(Updater.getInfo()))
			Updater.addEvent('loaded', self.fillVersion.bind(self));

		self.settings.createGroup({
			'name': 'CouchPotato'
		}).inject(self.content).adopt(
			new Element('div.usenet').adopt(
				new Element('div.text').adopt(
					new Element('span', {
						'text': 'This is a maintained fork of CouchPotato. '
					}),
					new Element('a', {
						'href': 'https://github.com/bassings/CouchPotatoServer',
						'target': '_blank',
						'text': 'View on GitHub'
					}),
					new Element('span', {
						'text': ' \u2014 bug reports, feature requests and contributions welcome.'
					})
				)
			)
		);

	},

	fillVersion: function(json){
		if(!json) return;
		var self = this;
		var date = new Date(json.version.date * 1000);
		self.version_text.set('text', json.version.hash + (json.version.date ? ' ('+date.toLocaleString()+')' : ''));
		self.updater_type.set('text', (json.version.type != json.branch) ? (json.version.type + ', ' + json.branch) : json.branch);
	}

});

window.addEvent('domready', function(){
	new AboutSettingTab();
});

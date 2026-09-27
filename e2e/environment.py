"""Settings for an end-to-end test environment.

Environments are sections of ~/.config/lambdamlm-test/e2e.ini (override with
LAMBDAMLM_E2E_CONFIG); see e2e/e2e.example.ini.
"""

import configparser
import os

CONFIG_PATH = os.environ.get('LAMBDAMLM_E2E_CONFIG',
                             os.path.expanduser('~/.config/lambdamlm-test/e2e.ini'))

# Resources created for testing carry this tag, so teardown can find them.
TAG_KEY = 'lambdamlm:e2e'
RULE_PREFIX = 'lambdamlm-e2e-'


class Environment(object):
    def __init__(self, name, section):
        self.name = name
        self.profile = section['profile']
        self.region = section['region']
        self.rule_set = section['rule_set']
        self.list_bucket = section['list_bucket']
        self.inboxes = [a.strip() for a in section['inboxes'].split(',') if a.strip()]
        self.function = section.get('function')
        self._inbox_bucket = section.get('inbox_bucket')
        self._session = None

    @property
    def session(self):
        if self._session is None:
            import boto3
            self._session = boto3.Session(profile_name=self.profile, region_name=self.region)
        return self._session

    def client(self, service):
        return self.session.client(service)

    @property
    def account(self):
        return self.client('sts').get_caller_identity()['Account']

    @property
    def inbox_bucket(self):
        return self._inbox_bucket or 'lambdamlm-e2e-inbox-{}-{}'.format(self.account, self.region)

    def inbox_prefix(self, address):
        return 'inbox/{}/'.format(address.lower())


def load(name, path=CONFIG_PATH):
    config = configparser.ConfigParser(interpolation=None)
    if not config.read(path):
        raise SystemExit('No e2e environment file at {}; see e2e/e2e.example.ini.'.format(path))
    if name not in config:
        raise SystemExit('No environment [{}] in {}.'.format(name, path))
    return Environment(name, config[name])

########
# Copyright (c) 2016 GigaSpaces Technologies Ltd. All rights reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
#    * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    * See the License for the specific language governing permissions and
#    * limitations under the License.

import os
import sys
import logging

import requests

from . import logger, repo, utils, constants

GITHUB_API_URL = 'https://api.github.com/{0}/{1}'
REPO_DETAILS_API_URL = \
    'https://api.github.com/{0}/{1}/repos?type={2}&per_page={3}&page={4}'


lgr = logger.init()


class Organization(object):
    def __init__(
            self,
            search_list,
            organization,
            git_user=None,
            git_password=None,
            print_result=False,
            is_organization=True,
            repos_to_skip=None,
            repos_to_check=None,
            consolidate_log=False,
            cloned_repos_path=None,
            results_dir=constants.RESULTS_PATH,
            verbose=False,
            remove_cloned_dir=False,
            **kwargs):
        self.print_result = print_result
        self.search_list = search_list
        self.organization = organization
        self.results_dir = results_dir
        if repos_to_skip and repos_to_check:
            lgr.warn('You can not both include and exclude repositories.')
            sys.exit(1)
        self.repos_to_skip = repos_to_skip
        self.repos_to_check = repos_to_check
        if not git_user or not git_password:
            lgr.warn(
                'Choosing not to provide GitHub credentials limits '
                'requests to GitHub to 60/h. This might affect cloning.')
            self.creds = False
        else:
            self.creds = (git_user, git_password)
        self.remove_cloned_dir = remove_cloned_dir
        self.results_file_path = os.path.join(
            results_dir, self.organization, 'results.json')
        self.consolidate_log = consolidate_log
        self.is_organization = is_organization
        self.item_type = 'orgs' if is_organization else 'users'
        self.cloned_repos_path = cloned_repos_path or os.path.join(
            self.organization, constants.CLONED_REPOS_PATH)
        self.verbose = verbose

        lgr.setLevel(logging.DEBUG if verbose else logging.INFO)

    @classmethod
    def init_with_config_file(cls, config_file, verbose=False,
                              print_result=False,
                              remove_cloned_dir=False,
                              is_organization=True):
        conf_vars = utils.read_config_file(
            config_file=config_file,
            print_result=print_result,
            verbose=verbose,
            remove_cloned_dir=remove_cloned_dir,
            is_organization=is_organization)
        return cls(**conf_vars)

    def _get_org_data(self):
        response = requests.get(GITHUB_API_URL.format(
            self.item_type, self.organization), auth=self.creds)
        if response.status_code == requests.codes.NOT_FOUND:
            lgr.error(
                'The organization or user {0} could not be found. '
                'Please make sure you use the correct type (org/user).'.format(
                    self.organization))
            sys.exit(1)
        return response.json()

    def _get_repo_data(self, repos_per_page, page_num):
        response = requests.get(REPO_DETAILS_API_URL.format(
            self.item_type,
            self.organization,
            'public',
            repos_per_page,
            page_num), auth=self.creds)
        return response.json()

    def _parse_repo_data(self, repo_data):
        return [dict((key, data[key]) for key in ['name', 'clone_url'])
                for data in repo_data]

    def _get_repos_data(self, repos_per_page=100):
        lgr.info('Retrieving repository information for the {0}...'.format(
            'organization' if self.is_organization else 'user'))
        org_data = self._get_org_data()
        repo_count = org_data['public_repos']
        last_page_number = repo_count / repos_per_page
        if (repo_count % repos_per_page) > 0:
            # Adding 2 because 1 for the extra repos that mean more page,
            #  and 1 for the next for loop.
            last_page_number += 2
            repos_data = []
            for page_num in range(1, last_page_number):
                repo_data = self._get_repo_data(repos_per_page, page_num)
                repos_data.extend(self._parse_repo_data(repo_data))
            return repos_data

    def get_include_list(self, repos_data, include=None, exclude=None):
        repo_url_list = []
        if include:
            for repo_name in include:
                for repo in repos_data:
                    if repo['name'] == repo_name:
                        repo_url_list.append(repo['clone_url'])
        elif exclude:
            for repo in repos_data:
                if repo['name'] not in exclude:
                    repo_url_list.append(repo['clone_url'])
        else:
            for repo in repos_data:
                repo_url_list.append(repo['clone_url'])
        return repo_url_list

    def search(self, search_list):
        search_list = search_list or self.search_list
        if len(search_list) == 0:
            lgr.error('You must supply at least one string to search for.')
            sys.exit(1)
        repos_data = self._get_repos_data()
        if not os.path.isdir(self.cloned_repos_path):
            os.makedirs(self.cloned_repos_path)
        utils.handle_results_file(self.results_file_path, self.consolidate_log)

        repos_url_list = self.get_include_list(repos_data=repos_data,
                                               include=self.repos_to_check,
                                               exclude=self.repos_to_skip)
        for repo_data in repos_url_list:
            repo.search(
                search_list=search_list,
                repo_url=repo_data,
                cloned_repo_dir=self.cloned_repos_path,
                results_dir=self.results_dir,
                print_result=False,
                remove_cloned_dir=False,
                consolidate_log=True,
                verbose=self.verbose)
        if self.remove_cloned_dir:
            utils.remove_repos_folder(path=self.cloned_repos_path)
        if self.print_result:
            utils.print_result(self.results_file_path)


def search(
        search_list,
        organization,
        git_user=None,
        git_password=None,
        repos_to_skip=None,
        repos_to_check=None,
        is_organization=True,
        config_file=None,
        cloned_repos_path=constants.CLONED_REPOS_PATH,
        results_dir=constants.RESULTS_PATH,
        print_result=False,
        remove_cloned_dir=False,
        verbose=False,
        **kwargs):

    if config_file:
        org = Organization.init_with_config_file(
            config_file=config_file,
            print_result=print_result,
            verbose=verbose,
            remove_cloned_dir=remove_cloned_dir,
            is_organization=is_organization)
    else:
        org = Organization(
            print_result=print_result,
            search_list=search_list,
            organization=organization,
            git_user=git_user,
            is_organization=is_organization,
            git_password=git_password,
            repos_to_skip=repos_to_skip,
            repos_to_check=repos_to_check,
            cloned_repos_path=cloned_repos_path,
            results_dir=results_dir,
            remove_cloned_dir=remove_cloned_dir,
            verbose=verbose)

    org.search(search_list=search_list)

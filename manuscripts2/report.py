#!/usr/bin/python3
# -*- coding: utf-8 -*-
#
# Copyright (C) 2018 CHAOSS
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.
#
# Author:
#   Pranjal Aswani <aswani.pranjal@gmail.com>
#

import sys
import os
import logging

from collections import defaultdict

import matplotlib
import matplotlib.pyplot as plt
from matplotlib.pyplot import figure
# Plot figures in style similar to 'seaborn'
plt.style.use('seaborn')
import pandas as pd

from elasticsearch import Elasticsearch

from .elasticsearch import (Query,
                            Index,
                            get_trend)

from .metrics import git
from .metrics import github_prs
from .metrics import github_issues

from .utils import str_val

logger = logging.getLogger(__name__)


def create_csv(filename, csv_data, mode="w"):
    """
    Create a CSV file with the given data and store it in the
    file with the given name.

    :param filename: name of the file to store the data in
    :pram csv_data: the data to be stored in the file
    :param mode: the mode in which we have to open the file. It can
                 be 'w', 'a', etc. Default is 'w'
    """

    with open(filename, mode) as f:
        csv_data.replace("_", r"\_")
        f.write(csv_data)


class Report():

    # Elasticsearch index names in which metrics data is stored
    GIT_INDEX = 'git'
    GITHUB_ISSUES_INDEX = 'github_issues'
    GITHUB_PRS_INDEX = 'github_prs'

    # Helper dict to map a data source class with its Elasticsearch index
    class2index = {
        git: GIT_INDEX,
        github_issues: GITHUB_ISSUES_INDEX,
        github_prs: GITHUB_PRS_INDEX
    }

    # Helper dict to map a data source name with its python class
    ds2class = {val: key for key, val in class2index.items()}

    def __init__(self, es_url=None, start=None, end=None, data_dir=None, filters=None,
                 interval="month", offset=None, data_sources=None,
                 report_name=None, projects=False, indices=[], logo=None):
        """
        Report init method called when creating a new Report object.

        :param es_url: Elasticsearch URL in which metrics data is stored
        :param start: start (from) date from which to compute the metrics
        :param end: end (to) date form which to compute the metrics
        :param data_dir: directory in which to store the data results for the report
        :param filters: additional filters to be added to all metrics queries
        :param interval: time interval used in Elasticsearch to aggregate the metrics data
        :param offset: time offset in days to be added to the intervals
        :param data_sources: list of data sources to be included in the report
        :param report_name: name of the report (used in the title for example)
        :param projects: generate a specific report for each project
        :param indices: list of data source indices in Elasticsearch to be used to get the metrics values
        :param logo: logo to be used in the report (in the title and headers of the pages)
        """

        self.es = es_url
        self.es_client = Elasticsearch(self.es)

        # Set the interval for all the metrics that are being calculated
        Query.interval_ = interval
        self.interval = interval

        # Set the client for all metrics that are being calculated
        Index.es = self.es_client

        self.start_date = start
        self.end_date = end
        self.data_dir = data_dir
        self.data_sources = data_sources

        self.index_dict = defaultdict(lambda: None)
        for pos, index in enumerate(indices):
            self.index_dict[data_sources[pos]] = index

    def get_metric_index(self, data_source):
        """
        This function will return the elasticsearch index for a corresponding
        data source. It chooses in between the default and the user inputed
        es indices and returns the user inputed one if it is available.

        :param data_source: the data source for which the index has to be returned
        :returns: an elasticsearch index name
        """

        if data_source in self.index_dict:
            index = self.index_dict[data_source]
        else:
            index = self.class2index[self.ds2class[data_source]]
        return Index(index_name=index)

    def get_sec_overview(self):
        """
        Generate the "overview" section of the report.
        """

        logger.debug("Calculating Overview metrics.")

        data_path = os.path.join(self.data_dir, "overview")
        if not os.path.exists(data_path):
            os.makedirs(data_path)

        overview_config = {
            "activity_metrics": [],
            "author_metrics": [],
            "bmi_metrics": [],
            "time_to_close_metrics": [],
            "projects_metrics": []
        }

        for ds in self.data_sources:
            metric_file = self.ds2class[ds]
            metric_index = self.get_metric_index(ds)
            overview = metric_file.overview(metric_index, self.start_date, self.end_date)
            for section in overview_config:
                overview_config[section] += overview[section]

        overview_config['activity_file_csv'] = "data_source_evolution.csv"
        overview_config['efficiency_file_csv'] = "efficiency.csv"

        # ACTIVITY METRICS
        metrics = overview_config['activity_metrics']
        file_name = overview_config['activity_file_csv']
        file_name = os.path.join(data_path, file_name)

        csv = "metricsnames, netvalues, relativevalues, datasource\n"

        for metric in metrics:
            (last, percentage) = get_trend(metric.timeseries())
            csv += "{}, {}, {}, {}\n".format(metric.name, last,
                                             percentage, metric.id)
        create_csv(file_name, csv)

        # AUTHOR METRICS
        """
        Git Authors:
        -----------
        Description: average number of developers per month by quarters
        (so we have the average number of developers per month during
        those three months). If the approach is to work at the level of month,
        then just the number of developers per month.
        """

        author = overview_config['author_metrics']
        if author:
            authors_by_period = author[0]
            title_label = file_label = authors_by_period.name + ' per ' + self.interval
            file_path = os.path.join(data_path, file_label)
            csv_data = authors_by_period.timeseries(dataframe=True)
            # generate the CSV and the image file displaying the data
            self.create_csv_fig_from_df([csv_data], file_path, [authors_by_period.name],
                                        fig_type="bar", title=title_label, xlabel="time_period",
                                        ylabel=authors_by_period.id)
        # BMI METRICS
        bmi = []
        bmi_metrics = overview_config['bmi_metrics']
        csv = ""
        for metric in bmi_metrics:
            bmi.append(metric.aggregations())
            csv += metric.id + ", "

        # Time to close METRICS
        ttc = []
        ttc_metrics = overview_config['time_to_close_metrics']
        for metric in ttc_metrics:
            ttc.append(metric.aggregations())
            csv += metric.id + ", "

        # generate efficiency file
        csv = csv[:-2] + "\n"
        csv = csv.replace("_", "")
        bmi.extend(ttc)
        for val in bmi:
            csv += "%s, " % str_val(val)
        if csv[-2:] == ", ":
            csv = csv[:-2]

        file_name = os.path.join(data_path, 'efficiency.csv')
        create_csv(file_name, csv)
        logger.debug("Overview metrics generation complete!")

    def get_sec_project_activity(self):
        """
        Generate the "project activity" section of the report.
        """

        logger.debug("Calculating Project Activity metrics.")

        data_path = os.path.join(self.data_dir, "project_activity")
        if not os.path.exists(data_path):
            os.makedirs(data_path)

        for ds in self.data_sources:
            metric_file = self.ds2class[ds]
            metric_index = self.get_metric_index(ds)
            project_activity = metric_file.project_activity(metric_index, self.start_date,
                                                            self.end_date)
            headers = []
            data_frames = []
            title_names = []
            file_name = ""
            for metric in project_activity['metrics']:
                file_name += metric_file.NAME + "_" + metric.id + "_"
                title_names.append(metric.name)
                headers.append(metric.id)
                data_frames.append(metric.timeseries(dataframe=True))

            file_name = file_name[:-1]  # remove trailing underscore
            file_path = os.path.join(data_path, file_name)
            title_name = " & ".join(title_names) + ' per ' + self.interval
            self.create_csv_fig_from_df(data_frames, file_path, headers,
                                        fig_type="bar", title=title_name)

    def create_csv_fig_from_df(self, data_frames=[], filename=None, headers=[], index_label=None,
                               fig_type=None, title=None, xlabel=None, ylabel=None, xfont=20,
                               yfont=20, titlefont=30, fig_size=(10, 15), image_type="png"):
        """
        Joins all the datafarames horizontally and creates a CSV and an image file from
        those dataframes.

        :param data_frames: a list of dataframes containing timeseries data from various metrics
        :param filename: the name of the csv and image file
        :param headers: a list of headers to be applied to columns of the dataframes
        :param index_label: name of the index column
        :param fig_type: figure type. Currently we support 'bar' graphs
                         default: normal graph
        :param title: display title of the figure
        :param filename: file name to save the figure as
        :param xlabel: label for x axis
        :param ylabel: label for y axis
        :param xfont: font size of x axis label
        :param yfont: font size of y axis label
        :param titlefont: font size of title of the figure
        :param fig_size: tuple describing size of the figure (in centimeters) (H x W)
        :param image_type: the image type to save the image as: jpg, png, etc
                           default: png

        :returns: creates a csv having name as "filename".csv and an image file
                  having the name as "filename"."image_type"
        """

        if not data_frames:
            logger.error("No dataframes provided to create CSV")
            sys.exit(1)
        assert(len(data_frames) == len(headers))
        dataframes = []

        for index, df in enumerate(data_frames):
            df = df.rename(columns={"value": headers[index]})
            dataframes.append(df)
        res_df = pd.concat(dataframes, axis=1)

        if "unixtime" in res_df:
            del res_df['unixtime']
        if not index_label:
            index_label = "Date"

        # Create the CSV file:
        csv_name = filename + ".csv"
        res_df.to_csv(csv_name, index_label=index_label)
        logger.debug("file: {} was created.".format(csv_name))

        # Create the Image:
        image_name = filename + "." + image_type
        figure(figsize=fig_size)
        plt.subplot(111)

        if fig_type == "bar":
            ax = res_df.plot.bar(figsize=fig_size)
            ticklabels = res_df.index
            ax.xaxis.set_major_formatter(matplotlib.ticker.FixedFormatter(ticklabels))
        else:
            plt.plot(res_df)

        if not ylabel:
            ylabel = "num " + " & ".join(headers)
        if not xlabel:
            xlabel = index_label

        plt.title(title, fontsize=titlefont)
        plt.ylabel(ylabel, fontsize=yfont)
        plt.xlabel(xlabel, fontsize=xfont)
        plt.grid(True)
        plt.savefig(image_name)
        logger.debug("Figure {} was generated.".format(image_name))
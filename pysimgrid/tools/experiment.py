# This file is part of pysimgrid, a Python interface to the SimGrid library.
#
# Copyright 2015-2016 Alexey Nazarenko and contributors
#
# This library is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# along with this library.  If not, see <http://www.gnu.org/licenses/>.
#

from __future__ import print_function

import argparse
import datetime
import fnmatch
import itertools
import json
import logging
import multiprocessing
import os
import time
from .. import simdag

def file_list(file_or_dir, masks=["*"]):
  if not os.path.exists(file_or_dir):
    raise Exception("path %s does not exist" % file_or_dir)
  if os.path.isdir(file_or_dir):
    result = []
    listing = os.listdir(file_or_dir)
    for fname in listing:
      if any((fnmatch.fnmatch(fname, pattern) for pattern in masks)):
        result.append(os.path.join(file_or_dir, fname))
    return result
  else:
    return [os.path.abspath(file_or_dir)]


def import_algorithm(algorithm):
  name_parts = algorithm.split(".")
  module_name = ".".join(name_parts[:-1])
  module = __import__(module_name)
  result = module
  for name in name_parts[1:]:
    result = getattr(result, name)
  assert isinstance(result, type)
  return result


def run_experiment(job):
  platform, tasks, algorithm = job
  # TODO: pass some configuration along the job
  logging.getLogger().setLevel(logging.WARNING)
  logger = logging.getLogger("pysimgrid.tools.Experiment")
  logger.info("Starting experiment (platform=%s, tasks=%s, algorithm=%s)", platform, tasks, algorithm["class"])
  scheduler_class = import_algorithm(algorithm["class"])
  clock = 0.
  try:
    with simdag.Simulation(platform, tasks, log_config="root.threshold:error") as simulation:
      scheduler = scheduler_class(simulation)
      scheduler.run()
      clock = simulation.clock
      exec_time = sum([t.finish_time - t.start_time for t in simulation.tasks])
      comm_time = sum([t.finish_time - t.start_time for t in simulation.all_tasks[simdag.TaskKind.TASK_KIND_COMM_E2E]])
      return job, clock, exec_time, comm_time
  except Exception:
    raise Exception("Simulation failed! Parameters: %s" % (job,))


def progress_reporter(iterable, length, logger):
  start_time = last_result_timestamp = time.time()
  average_time = 0.
  for idx, element in enumerate(iterable):
    current = time.time()
    elapsed = current - last_result_timestamp
    last_result_timestamp = current
    count = idx + 1
    average_time = average_time * (count - 1) / float(count) + elapsed / count
    remaining = (length - idx) * average_time
    eta_string = (" [ETA: %s]" % datetime.timedelta(seconds=remaining)) if idx > 10 else ""
    logger.info("%d/%d%s", idx + 1, length, eta_string)
    yield element
  logger.info("Finished. %d experiments in %f seconds", length, time.time() - start_time)


def main():
  _LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
  _LOG_FORMAT = "[%(name)s] [%(levelname)5s] [%(asctime)s] %(message)s"

  parser = argparse.ArgumentParser(description="Run experiments for a set of scheduling algorithms")
  parser.add_argument("platforms", type=str, help="path to file or directory containing platform definitions (*.xml)")
  parser.add_argument("tasks", type=str, help="path to file or directory containing task definitions (*.dax, *.dot)")
  parser.add_argument("algorithms", type=str, help="path to json defining the algorithms to use")
  parser.add_argument("output", type=str, help="path to the output file")
  parser.add_argument("-j", "--jobs", type=int, default=1, help="number of parallel jobs to run")
  args = parser.parse_args()

  logging.basicConfig(level=logging.DEBUG, format=_LOG_FORMAT, datefmt=_LOG_DATE_FORMAT)
  logger = logging.getLogger("Experiment")

  with open(args.algorithms, "r") as alg_file:
    algorithms = json.load(alg_file)
    if not isinstance(algorithms, list):
      algorithms = [algorithms]

  platforms = file_list(args.platforms)
  tasks = file_list(args.tasks)

  jobs = list(itertools.product(platforms, tasks, algorithms))
  results = []

  ctx = multiprocessing.get_context("spawn")
  with ctx.Pool(processes=args.jobs, maxtasksperchild=1) as pool:
    for job, makespan, exec_time, comm_time in progress_reporter(pool.imap_unordered(run_experiment, jobs, 1), len(jobs), logger):
      platform, tasks, algorithm = job
      results.append({
        "platform": platform,
        "tasks": tasks,
        "algorithm": algorithm,
        "makespan": makespan,
        "exec_time": exec_time,
        "comm_time": comm_time
      })


  with open(args.output, "w") as out_file:
    json.dump(results, out_file)


if __name__ == "__main__":
  main()
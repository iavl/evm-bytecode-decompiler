pragma solidity ^0.8.0;
contract CustomErrorFixture { error TooSmall(uint256 value); function check(uint256 value) external pure { if (value < 2) revert TooSmall(value); } }
